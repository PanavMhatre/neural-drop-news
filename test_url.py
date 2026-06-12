import logging
from src.pipeline import Pipeline

logging.basicConfig(level=logging.INFO, format="%(message)s")

def run_url_test():
    pipeline = Pipeline()
    
    # We use a URL to skip the bulk LLM scoring phase which hits Cerebras 429 limits
    url = "https://techcrunch.com/2026/06/01/the-duckduckgo-surge-as-users-flee-ai-search/"
    
    print(f"Testing pipeline with recent tech news URL: {url}")
    
    # Pass the URL as the topic, which skips the scoring and focuses on exactly this article
    packages = pipeline.generate(count=1, overrides={"topic": url, "custom_video_url": url})
    
    if packages:
        pkg = packages[0]
        print(f"\n--- TEST COMPLETE ---")
        print(f"Package ID: {pkg.package_id}")
        print(f"Quality Verdict: {pkg.quality_report.verdict}")
        print(f"Quality Score: {pkg.quality_report.overall_score}")
        print(f"Output Video Path: {pkg.video_path}")
        print(f"Is Scheduled? Let's check DB.")
        
        # Manually schedule it since we skipped the autonomous agent wrapper
        if pkg.quality_report.verdict == "approved":
            from src.memory.database import Database
            from datetime import datetime, timedelta
            db = Database()
            scheduled_time = (datetime.now() + timedelta(hours=2)).isoformat()
            db.schedule_post(pkg.package_id, scheduled_time)
            print(f"Successfully queued in Auto-Publisher for {scheduled_time}!")
            
if __name__ == "__main__":
    run_url_test()
