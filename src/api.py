import json
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv

from src.buffer_client import (
    BufferClient,
    BufferError,
    build_post_text,
    build_service_text_map,
    is_public_url,
    package_public_url,
)
from src.memory.database import Database
from src.pipeline import Pipeline
from src.agent import AutonomousAgent
from src.publisher import AutoPublisher
from src.public_media import PublicMediaError, public_assets_for_package

load_dotenv()

logger = logging.getLogger(__name__)

app = FastAPI(title="TechPulse Shorts API")

agent_daemon = AutonomousAgent()
publisher_daemon = AutoPublisher()

@app.on_event("startup")
def startup_event():
    publisher_daemon.start()

@app.on_event("shutdown")
def shutdown_event():
    agent_daemon.stop()
    publisher_daemon.stop()

# Enable CORS for local Vite dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = "./data/news_shorts.db"
OUTPUT_DIRS = ["./output", "./demo/example_output"]

progress_store = {}


class ScheduleRequest(BaseModel):
    scheduled_time: str  # ISO format string

class RenderOptions(BaseModel):
    topic: Optional[str] = None
    custom_video_url: Optional[str] = None
    accent_color_hex: Optional[str] = None
    tts_voice: Optional[str] = None

def get_db():
    return Database(db_path=DB_PATH)

def find_package_dir(package_id: str) -> Path | None:
    """Return a package directory only if it lives directly under a known output dir."""
    for out_dir in OUTPUT_DIRS:
        base_path = Path(out_dir).resolve()
        package_dir = (base_path / package_id).resolve()
        try:
            package_dir.relative_to(base_path)
        except ValueError:
            continue
        if package_dir.exists() and package_dir.is_dir():
            return package_dir
    return None

def get_public_media_base_url() -> str:
    base_url = os.getenv("BUFFER_PUBLIC_MEDIA_BASE_URL") or os.getenv("PUBLIC_MEDIA_BASE_URL")
    if not base_url or not is_public_url(base_url):
        raise HTTPException(
            status_code=400,
            detail=(
                "Set BUFFER_PUBLIC_MEDIA_BASE_URL to a public HTTPS URL for this API "
                "before scheduling videos through Buffer."
            ),
        )
    return base_url.rstrip("/")

def get_public_package_media(package_dir: Path) -> tuple[str, str | None]:
    try:
        manifest = public_assets_for_package(package_dir)
    except PublicMediaError as e:
        raise HTTPException(status_code=502, detail=str(e))

    video_url = manifest.get("assets", {}).get("video.mp4", {}).get("url")
    thumbnail_url = manifest.get("assets", {}).get("thumbnail.png", {}).get("url")
    if not video_url or not is_public_url(video_url):
        raise HTTPException(status_code=502, detail="Video upload did not produce a public HTTPS URL")
    if thumbnail_url and not is_public_url(thumbnail_url):
        thumbnail_url = None
    return video_url, thumbnail_url

@app.get("/api/progress")
def get_progress():
    """Get active progress for all currently rendering tasks."""
    return progress_store


@app.get("/api/videos")
def list_videos():
    """List all generated videos from output directories."""
    videos = []
    for out_dir in OUTPUT_DIRS:
        base_path = Path(out_dir)
        if not base_path.exists():
            continue
            
        for package_dir in base_path.iterdir():
            if package_dir.name == ".DS_Store" or not package_dir.is_dir():
                continue
                
            metadata_path = package_dir / "metadata.json"
            if not metadata_path.exists():
                continue
                
            try:
                with open(metadata_path, "r") as f:
                    metadata = json.load(f)
                    
                video_file = package_dir / "video.mp4"
                has_video = video_file.exists()
                
                videos.append({
                    "id": package_dir.name,
                    "title": metadata.get("title_options", ["Untitled"])[0],
                    "description": metadata.get("description", ""),
                    "hashtags": metadata.get("hashtags", []),
                    "has_video": has_video,
                    "created_at": datetime.fromtimestamp(package_dir.stat().st_ctime).isoformat(),
                    "output_dir": out_dir
                })
            except Exception as e:
                logger.error(f"Failed to parse metadata for {package_dir.name}: {e}")
                
    # Sort by newest first
    videos.sort(key=lambda x: x["created_at"], reverse=True)
    return {"videos": videos}


@app.get("/api/videos/{package_id}")
def get_video_details(package_id: str):
    """Get full details for a specific video package."""
    for out_dir in OUTPUT_DIRS:
        package_dir = Path(out_dir) / package_id
        if package_dir.exists():
            try:
                with open(package_dir / "metadata.json", "r") as f:
                    metadata = json.load(f)
                with open(package_dir / "script.json", "r") as f:
                    script = json.load(f)
                with open(package_dir / "quality_report.json", "r") as f:
                    quality = json.load(f)
                    
                return {
                    "id": package_id,
                    "metadata": metadata,
                    "script": script,
                    "quality_report": quality,
                    "has_video": (package_dir / "video.mp4").exists()
                }
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
                
    raise HTTPException(status_code=404, detail="Package not found")


@app.delete("/api/videos/{package_id}")
def delete_video(package_id: str):
    """Delete one generated video package from the local output folders."""
    package_dir = find_package_dir(package_id)
    if not package_dir:
        raise HTTPException(status_code=404, detail="Package not found")

    try:
        shutil.rmtree(package_dir)
        db = get_db()
        try:
            db.delete_scheduled_post(package_id)
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Failed to delete package {package_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    progress_store.pop(package_id, None)
    return {"status": "deleted", "package_id": package_id}


@app.get("/media/{package_id}/{filename}")
def get_media(package_id: str, filename: str):
    """Serve media files (video.mp4, thumbnail.png)."""
    for out_dir in OUTPUT_DIRS:
        file_path = Path(out_dir) / package_id / filename
        if file_path.exists():
            return FileResponse(str(file_path))
            
    raise HTTPException(status_code=404, detail="File not found")


@app.get("/api/schedule")
def get_schedule():
    """Get all scheduled posts."""
    db = get_db()
    try:
        scheduled = db.get_scheduled_posts()
        return {"scheduled": scheduled}
    finally:
        db.close()


@app.post("/api/schedule/{package_id}")
def schedule_video(package_id: str, req: ScheduleRequest):
    """Schedule a video through Buffer for the NeuralDropBits account."""
    package_dir = find_package_dir(package_id)
    if not package_dir:
        raise HTTPException(status_code=404, detail="Package not found")
    if not (package_dir / "video.mp4").exists():
        raise HTTPException(status_code=400, detail="Package has no rendered video.mp4")

    try:
        public_base_url = get_public_media_base_url()
        video_url = package_public_url(public_base_url, package_id, "video.mp4")
        thumbnail_url = package_public_url(public_base_url, package_id, "thumbnail.png")
    except HTTPException:
        video_url, thumbnail_url = get_public_package_media(package_dir)
    post_text = build_post_text(package_dir)
    text_by_service = build_service_text_map(package_dir)

    db = get_db()
    try:
        results = BufferClient().create_scheduled_video_posts(
            text=post_text,
            text_by_service=text_by_service,
            due_at=req.scheduled_time,
            video_url=video_url,
            thumbnail_url=thumbnail_url,
        )
        posts = [result["post"] for result in results]
        channels = [result["channel"] for result in results]
        channel_names = [
            f"{channel.get('displayName') or channel.get('name')} ({channel.get('service')})"
            for channel in channels
        ]
        db.schedule_post(
            package_id,
            req.scheduled_time,
            status="buffer_scheduled",
            buffer_post_id=", ".join(post["id"] for post in posts),
            buffer_channel_id=", ".join(channel["id"] for channel in channels),
            buffer_channel_name=", ".join(channel_names),
            buffer_status="scheduled",
        )
        return {
            "status": "success",
            "package_id": package_id,
            "scheduled_time": req.scheduled_time,
            "buffer_post_ids": [post["id"] for post in posts],
            "buffer_channels": channel_names,
        }
    except BufferError as e:
        db.schedule_post(
            package_id,
            req.scheduled_time,
            status="buffer_failed",
            buffer_status="failed",
            buffer_error=str(e),
        )
        raise HTTPException(status_code=502, detail=str(e))
    finally:
        db.close()


@app.get("/api/buffer/status")
def get_buffer_status():
    """Verify the configured Buffer target channels without creating posts."""
    try:
        channels = BufferClient().resolve_target_channels()
        return {
            "status": "connected",
            "channels": [
                {
                    "id": channel.get("id"),
                    "channel": channel.get("displayName") or channel.get("name"),
                    "service": channel.get("service"),
                    "is_queue_paused": channel.get("isQueuePaused"),
                }
                for channel in channels
            ],
        }
    except BufferError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/api/upload")
async def upload_video(file: UploadFile = File(...)):
    """Upload a custom B-Roll video."""
    upload_dir = Path("./data/uploads")
    upload_dir.mkdir(parents=True, exist_ok=True)
    
    file_path = upload_dir / file.filename
    with open(file_path, "wb") as buffer:
        import shutil
        shutil.copyfileobj(file.file, buffer)
        
    # Return absolute file uri format so the backend parser handles it correctly
    return {"status": "success", "file_path": f"file://{file_path.absolute()}"}


def run_pipeline_task(options: RenderOptions):
    """Run the pipeline in the background."""
    try:
        pipeline = Pipeline()
        pipeline.generate(count=1, overrides=options.model_dump())
    except Exception as e:
        logger.error(f"Pipeline background task failed: {e}")


@app.post("/api/generate")
def trigger_generation(background_tasks: BackgroundTasks, options: RenderOptions):
    """Trigger a new video generation run with options."""
    background_tasks.add_task(run_pipeline_task, options)
    return {"status": "started", "message": "Video generation started in background."}


class ReRenderOptions(BaseModel):
    script_text: Optional[str] = None
    custom_video_url: Optional[str] = None
    accent_color_hex: Optional[str] = None
    tts_voice: Optional[str] = None

def run_re_render_task(package_id: str, overrides: dict):
    progress_store[package_id] = 0
    try:
        def cb(p):
            progress_store[package_id] = p
        pipeline = Pipeline()
        pipeline.re_render_package(package_id, overrides, progress_callback=cb)
    except Exception as e:
        logger.error(f"Re-render background task failed: {e}")
    finally:
        if package_id in progress_store:
            del progress_store[package_id]

@app.post("/api/videos/{package_id}/render")
def trigger_re_render(package_id: str, background_tasks: BackgroundTasks, options: ReRenderOptions):
    """Trigger a re-render of an existing video with overrides."""
    background_tasks.add_task(run_re_render_task, package_id, options.model_dump())
    return {"status": "started", "message": "Re-render started in background."}

@app.post("/api/agent/start")
def start_agent():
    agent_daemon.start()
    return {"status": "success", "message": "Autonomous Agent started."}

@app.post("/api/agent/stop")
def stop_agent():
    agent_daemon.stop()
    return {"status": "success", "message": "Autonomous Agent stopped."}

@app.get("/api/agent/status")
def get_agent_status():
    return {"is_running": agent_daemon.is_running}


# ---------------------------------------------------------------------------
# Curator Intelligence Brief
# ---------------------------------------------------------------------------

@app.get("/api/curator/brief")
def get_curator_brief():
    """
    Returns a full intelligence brief for the Neural Drop News Curator Cloud.

    The curator calls this before selecting stories. It gets:
      - top_keywords: topics that are currently performing well on the channel
      - avoid_topics: topics recently overrepresented (dedup signals)
      - avg_engagement_30d: baseline to beat
      - top_videos: the 5 best clips by views in the last 30 days
      - zernio_top: top-performing topics from Zernio (cross-platform)
      - recent_titles: last 10 produced titles so the curator avoids repeats
      - recommended_formats: which video formats (broll_source) are working

    The curator uses this to build a ranked --manifest JSON that the pipeline
    ingests with priority scores and topic affinity already embedded.
    """
    import os
    from src.analytics.youtube_channel import YouTubeChannelAnalytics
    from src.analytics import zernio

    yt = YouTubeChannelAnalytics(api_key=os.getenv("YOUTUBE_API_KEY", ""))

    # Resolve channel ID
    channel_id = os.getenv("YOUTUBE_CHANNEL_ID", "")
    if not channel_id:
        channel_id = yt.get_channel_id("NeuralDropBits") or ""

    yt_insights: dict = {}
    if channel_id:
        try:
            yt_insights = yt.get_performance_insights(channel_id)
        except Exception as e:
            logger.warning(f"YT insights failed: {e}")

    # Zernio top topics
    zernio_topics = zernio.get_topic_performance()
    zernio_top = sorted(zernio_topics.items(), key=lambda x: x[1], reverse=True)[:8]

    # Recent titles from DB to avoid repeats
    db = get_db()
    try:
        recent = db.get_recent_packages(limit=10)
        recent_titles = [r.get("title", "") for r in recent if r.get("title")]
    except Exception:
        recent_titles = []
    finally:
        db.close()

    # Build topic boost map: union of YT keywords + Zernio
    topic_boosts: dict[str, float] = {}
    for kw, score in yt_insights.get("top_keywords", []):
        topic_boosts[kw] = topic_boosts.get(kw, 0) + score
    for topic, score in zernio_top:
        topic_boosts[topic] = topic_boosts.get(topic, 0) + score * 10

    # Normalize to 0-100
    max_boost = max(topic_boosts.values(), default=1)
    topic_boosts_norm = {k: round(v / max_boost * 100) for k, v in topic_boosts.items()}

    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "channel": "NeuralDropBits",

        # What's working — curator should prioritise stories mentioning these
        "top_keywords": sorted(topic_boosts_norm.items(), key=lambda x: x[1], reverse=True)[:12],

        # Raw channel data
        "avg_views_30d": yt_insights.get("avg_views_30d", 0),
        "avg_engagement_30d": yt_insights.get("avg_engagement_30d", 0),
        "top_videos": yt_insights.get("top_videos", []),

        # Cross-platform performance from Zernio
        "zernio_top_topics": [{"topic": t, "score": round(s, 2)} for t, s in zernio_top],

        # Titles recently produced — curator should avoid near-duplicates
        "recent_titles": recent_titles,

        # Curator manifest format hint
        "manifest_schema": {
            "description": "POST to /api/curator/manifest or pass as --manifest to run_daily.py",
            "fields": {
                "article_url": "string — primary article URL",
                "video_url": "string — optional direct video URL",
                "title": "string — story headline",
                "topic_affinity": "float 0-1 — how well this matches top_keywords",
                "priority": "int 1-10 — curator-assigned priority (10=highest)",
                "reason": "string — why curator selected this story",
            },
        },
    }


@app.post("/api/curator/manifest")
def receive_curator_manifest(background_tasks: BackgroundTasks, payload: dict):
    """
    Receive a manifest from the Neural Drop News Curator Cloud and kick off
    the pipeline immediately in the background.

    Expected payload:
      {
        "count": 7,
        "stories": [
          {"article_url": "...", "title": "...", "priority": 9, "topic_affinity": 0.87},
          ...
        ]
      }

    Stories are sorted by priority before processing so the best ones always
    make it into the daily batch even if the pipeline runs out of time.
    """
    import json

    stories = payload.get("stories", [])
    count = int(payload.get("count", 7))

    if not stories:
        raise HTTPException(status_code=400, detail="No stories in manifest")

    # Sort by curator priority descending
    stories_sorted = sorted(stories, key=lambda s: s.get("priority", 5), reverse=True)
    manifest_json = json.dumps(stories_sorted)

    def _run():
        from src.pipeline import Pipeline
        p = Pipeline()
        from run_daily import main as _main
        _main(count=count, manifest=manifest_json)

    background_tasks.add_task(_run)
    logger.info(f"Curator manifest received: {len(stories)} stories, top priority={stories_sorted[0].get('priority')}")
    return {
        "status": "accepted",
        "story_count": len(stories),
        "processing_count": min(count, len(stories)),
        "top_story": stories_sorted[0].get("title", ""),
    }
