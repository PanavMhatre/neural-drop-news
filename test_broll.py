import logging
from src.video.smart_broll import SmartBRollAgent
from src.models.schemas import RawStory, GeneratedScript, ScriptSection, VisualCue
from src.pipeline import Pipeline
from pathlib import Path

logging.basicConfig(level=logging.INFO)

pipeline = Pipeline("config.yaml")

script = GeneratedScript(
    sections=ScriptSection(
        hook="", main_explanation="", why_it_matters="", student_dev_angle="", closing_line=""
    ),
    full_script="Test script about Apple Vision Pro.",
    word_count=1, estimated_duration_seconds=10.0,
    structure_type="company_move",
    visual_plan=[VisualCue(section="hook", description="Tim Cook says good morning", text_overlay="APPLE EVENT")],
    caption_lines=["Apple"],
    title_ideas=["Test1", "Test2", "Test3"], description="", hashtags=[], source_list=[], commentary_notes=""
)

story = RawStory(
    title="Apple Event", url="https://www.youtube.com/watch?v=1La4QzGeaaQ", 
    source_name="YouTube", snippet="", published_at=None, categories=[]
)

agent = SmartBRollAgent("./demo/test_broll", pipeline.openai_client)
paths = agent.acquire_media(script, story)
print(paths)
