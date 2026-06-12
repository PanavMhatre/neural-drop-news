import time
import logging
import threading
from datetime import datetime, timedelta
from typing import Optional

from src.pipeline import Pipeline
from src.memory.database import Database

logger = logging.getLogger(__name__)

class AutonomousAgent:
    """
    Background agent that autonomously discovers news, generates videos,
    and schedules them if they meet quality thresholds.
    """
    
    def __init__(self, check_interval_seconds: int = 3600, schedule_delay_hours: int = 2):
        self.check_interval = check_interval_seconds
        self.schedule_delay_hours = schedule_delay_hours
        self.is_running = False
        self._thread: Optional[threading.Thread] = None
        self.db = Database(db_path="./data/news_shorts.db")
        
    def start(self):
        """Start the autonomous agent loop in a background thread."""
        if self.is_running:
            return
            
        self.is_running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("Autonomous Agent started.")
        
    def stop(self):
        """Stop the autonomous agent."""
        self.is_running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        logger.info("Autonomous Agent stopped.")
        
    def run_once(self):
        """Run a single iteration of the autonomous pipeline."""
        logger.info("Agent: Running autonomous generation cycle...")
        try:
            pipeline = Pipeline()
            
            # 1. Generate 1 video autonomously
            packages = pipeline.generate(count=1)
            
            if not packages:
                logger.info("Agent: No packages generated this cycle.")
                return
                
            package = packages[0]
            package_id = package.package_id
            
            # 2. Self-Approval Gate
            if package.quality_report.verdict == "approved":
                logger.info(f"Agent: Package {package_id} approved by AI! Scheduling...")
                
                # Schedule for a few hours in the future
                scheduled_time = (datetime.now() + timedelta(hours=self.schedule_delay_hours)).isoformat()
                
                # 3. Queue into scheduling buffer
                self.db.schedule_post(package_id, scheduled_time)
                logger.info(f"Agent: Successfully scheduled {package_id} for {scheduled_time}")
            else:
                logger.info(f"Agent: Package {package_id} rejected (Score: {package.quality_report.overall_score}). Discarding.")
                
        except Exception as e:
            logger.error(f"Agent cycle failed: {e}")
            
    def _loop(self):
        """Infinite loop for the background thread."""
        while self.is_running:
            self.run_once()
            
            # Sleep in small increments to allow responsive stopping
            for _ in range(self.check_interval):
                if not self.is_running:
                    break
                time.sleep(1)
