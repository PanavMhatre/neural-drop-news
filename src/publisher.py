import time
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.memory.database import Database

logger = logging.getLogger(__name__)

class AutoPublisher:
    """
    Background daemon that checks the scheduled_posts table
    and uploads videos to configured platforms when their time arrives.
    """
    
    def __init__(self, check_interval_seconds: int = 60):
        self.check_interval = check_interval_seconds
        self.is_running = False
        self._thread: Optional[threading.Thread] = None
        self.db = Database(db_path="./data/news_shorts.db")
        
    def start(self):
        if self.is_running:
            return
        self.is_running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("Auto-Publisher started.")
        
    def stop(self):
        self.is_running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        logger.info("Auto-Publisher stopped.")
        
    def _post_to_youtube(self, video_path: str, metadata: dict) -> bool:
        """Stub for YouTube API integration."""
        logger.info(f"YOUTUBE UPLOAD STUB: Uploading {video_path}...")
        # TODO: Implement googleapiclient.discovery.build("youtube", "v3") here
        time.sleep(2) # Simulate upload time
        logger.info("YOUTUBE UPLOAD STUB: Upload complete!")
        return True
        
    def _post_to_tiktok(self, video_path: str, metadata: dict) -> bool:
        """Stub for TikTok API integration."""
        logger.info(f"TIKTOK UPLOAD STUB: Uploading {video_path}...")
        # TODO: Implement TikTok Content Posting API here
        time.sleep(2)
        logger.info("TIKTOK UPLOAD STUB: Upload complete!")
        return True
        
    def run_once(self):
        """Check for due posts and publish them."""
        try:
            scheduled_posts = self.db.get_scheduled_posts()
            now = datetime.now()
            
            for post in scheduled_posts:
                if post["status"] != "queued":
                    continue
                    
                scheduled_time = datetime.fromisoformat(post["scheduled_time"])
                if now >= scheduled_time:
                    package_id = post["package_id"]
                    logger.info(f"Publisher: Time reached for {package_id}. Starting publish...")
                    
                    # Locate video file
                    video_path = None
                    for base_dir in ["./output", "./demo/example_output"]:
                        p = Path(base_dir) / package_id / "video.mp4"
                        if p.exists():
                            video_path = str(p)
                            break
                            
                    if not video_path:
                        logger.error(f"Publisher: Video file not found for {package_id}")
                        self.db._conn.execute("UPDATE scheduled_posts SET status = 'failed' WHERE package_id = ?", (package_id,))
                        self.db._conn.commit()
                        continue
                        
                    # Here we would load metadata to get the title/description
                    metadata = {"title": "TechPulse Short", "description": ""}
                    
                    # Execute uploads (Stubs)
                    yt_success = self._post_to_youtube(video_path, metadata)
                    tk_success = self._post_to_tiktok(video_path, metadata)
                    
                    if yt_success and tk_success:
                        self.db._conn.execute("UPDATE scheduled_posts SET status = 'published' WHERE package_id = ?", (package_id,))
                        self.db._conn.commit()
                        logger.info(f"Publisher: Successfully published {package_id}!")
                    else:
                        self.db._conn.execute("UPDATE scheduled_posts SET status = 'failed' WHERE package_id = ?", (package_id,))
                        self.db._conn.commit()
                        logger.error(f"Publisher: Failed to publish {package_id}")
                        
        except Exception as e:
            logger.error(f"Publisher cycle failed: {e}")
            
    def _loop(self):
        while self.is_running:
            self.run_once()
            
            for _ in range(self.check_interval):
                if not self.is_running:
                    break
                time.sleep(1)
