import logging
import asyncio
from src.pipeline import Pipeline
from src.models.schemas import RawStory, ScoredStory, StoryScore

logging.basicConfig(level=logging.INFO, format="%(message)s")

def run_mock_test():
    pipeline = Pipeline()
    
    mock_story = RawStory(
        title="OpenAI GPT-4o Spring Update Keynote Full Presentation",
        url="mock://openai",
        snippet="OpenAI announces GPT-4o with real-time voice, vision, and text.",
        content="OpenAI CTO Mira Murati unveiled GPT-4o during the Spring Update event. The new model can reason across audio, vision, and text in real time, and is twice as fast as GPT-4 Turbo. The live demonstration showcased the model's ability to interrupt, understand emotion, and even sing. The internet is losing its mind over the demo.",
        published_at="2026-06-01T12:00:00Z",
        source_name="OpenAI"
    )
    
    mock_score = StoryScore(
        freshness=100,
        source_credibility=90,
        relevance=95,
        viral_potential=98,
        educational_value=85,
        business_angle=80,
        visual_potential=90,
        explainability=100
    )
    
    scored_story = ScoredStory(
        story=mock_story,
        score=mock_score,
        accepted=True,
        detected_tone="general"
    )
    
    print(f"Testing pipeline with mock story: {mock_story.title}")
    
    # Run the processing pipeline
    package = pipeline.process_story(scored_story, overrides={
        "tts_voice": "en-US-JennyNeural", 
        "accent_color_hex": "#ffffff"
    })
    
    if package:
        print(f"\n--- TEST COMPLETE ---")
        print(f"Package ID: {package.package_id}")
        print(f"Quality Verdict: {package.quality_report.verdict}")
        print(f"Quality Score: {package.quality_report.overall_score}")
        print(f"Output Video Path: {package.video_path}")
        
        # Schedule it
        if package.quality_report.verdict == "approved":
            from src.memory.database import Database
            from datetime import datetime, timedelta
            db = Database()
            scheduled_time = (datetime.now() + timedelta(hours=2)).isoformat()
            db.schedule_post(package.package_id, scheduled_time)
            print(f"Successfully queued in Auto-Publisher for {scheduled_time}!")
            
if __name__ == "__main__":
    run_mock_test()
