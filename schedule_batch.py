import sys
import logging
from pathlib import Path
from dotenv import load_dotenv

# Set up logging to see upload progress
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

load_dotenv()

from src.public_media import public_assets_for_package
from src.buffer_client import BufferClient, build_post_text

def main():
    packages_and_times = [
        ("output/2026-06-01_anthropic-ipo-filing", "2026-06-02T09:00:00-05:00"),
        ("output/2026-06-01_duckduckgo-surges-as-users-flee-force-fed-ai-searc", "2026-06-02T13:30:00-05:00"),
        ("output/2026-06-01_motorola-dfend-counter-drone", "2026-06-02T15:00:00-05:00"),
        ("output/2026-06-01_softbank-france-ai-data-centers", "2026-06-02T16:30:00-05:00"),
        ("output/2026-06-01_real-tech-news-student-brief", "2026-06-02T18:00:00-05:00"),
    ]

    client = BufferClient()
    # Check if target channels resolve
    try:
        channels = client.resolve_target_channels()
        print(f"✓ Found {len(channels)} target channels in Buffer.")
    except Exception as e:
        print(f"Error resolving Buffer channels: {e}")
        sys.exit(1)

    for pkg_str, sched_time in packages_and_times:
        pkg_dir = Path(pkg_str)
        print(f"\n--- Processing {pkg_dir.name} ---")
        
        # 1. Upload to public media (Discord / GitHub)
        print("Uploading assets to public storage...")
        manifest = public_assets_for_package(pkg_dir)
        video_url = manifest.get("assets", {}).get("video.mp4", {}).get("url")
        thumbnail_url = manifest.get("assets", {}).get("thumbnail.png", {}).get("url")
        
        if not video_url:
            print("✗ Failed to get a public video URL.")
            continue
            
        print(f"✓ Public video URL ready: {video_url}")

        # 2. Build text
        text = build_post_text(pkg_dir)
        
        # 3. Schedule via Buffer
        print(f"Scheduling for {sched_time}...")
        try:
            results = client.create_scheduled_video_posts(
                text=text,
                due_at=sched_time,
                video_url=video_url,
                thumbnail_url=thumbnail_url
            )
            for result in results:
                ch = result["channel"]
                ch_name = ch.get("displayName") or ch.get("name")
                print(f"  ✓ Scheduled on {ch_name} ({ch.get('service')}) - Post ID: {result['post']['id']}")
        except Exception as e:
            print(f"  ✗ Failed to schedule: {e}")

if __name__ == "__main__":
    main()
