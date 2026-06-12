"""
CLI entry point for the AI + Tech News Shorts production system.

Usage:
    python -m src.cli generate --count 3
    python -m src.cli generate --topic "OpenAI GPT-5"
    python -m src.cli discover --count 10
    python -m src.cli review
    python -m src.cli demo
    python -m src.cli stats
"""

import json
import logging
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.logging import RichHandler

console = Console()


def setup_logging(level: str = "INFO"):
    """Configure logging with rich output."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True)],
    )


@click.group()
@click.option("--config", default="config.yaml", help="Path to config file")
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
@click.pass_context
def cli(ctx, config, verbose):
    """AI + Tech News Shorts Production System."""
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config
    setup_logging("DEBUG" if verbose else "INFO")


@cli.command()
@click.option("--topic", "-t", default=None, help="Specific topic to search for")
@click.option("--count", "-n", default=1, help="Number of videos to generate")
@click.pass_context
def generate(ctx, topic, count):
    """Generate video packages from news stories."""
    from src.pipeline import Pipeline

    console.print(f"\n[bold cyan]🎬 Generating {count} video(s)...[/bold cyan]\n")

    try:
        pipeline = Pipeline(config_path=ctx.obj["config_path"])
        packages = pipeline.generate(topic=topic, count=count)

        if packages:
            console.print(f"\n[bold green]✓ Generated {len(packages)} package(s):[/bold green]")
            for pkg in packages:
                console.print(f"  📦 {pkg.package_id}")
                console.print(f"     Title: {pkg.metadata.title_options[0] if pkg.metadata.title_options else 'N/A'}")
                console.print(f"     Quality: {pkg.quality_report.overall_score}/100")
                console.print(f"     Dir: {pkg.output_dir}")
        else:
            console.print("[yellow]No packages generated. Check logs for details.[/yellow]")
    except Exception as e:
        console.print(f"[red bold]Error: {e}[/red bold]")
        raise


@cli.command()
@click.option("--topic", "-t", default=None, help="Specific topic to search for")
@click.option("--count", "-n", default=10, help="Max stories to discover")
@click.pass_context
def discover(ctx, topic, count):
    """Discover and score stories (no rendering)."""
    from src.pipeline import Pipeline

    console.print(f"\n[bold cyan]🔍 Discovering stories...[/bold cyan]\n")

    pipeline = Pipeline(config_path=ctx.obj["config_path"])

    # Discover
    stories = pipeline.discover(topic=topic, max_results=count)
    console.print(f"Found {len(stories)} fresh stories\n")

    if not stories:
        return

    # Score
    scored = pipeline.score(stories)

    console.print(f"\n[bold]Results:[/bold]")
    for s in scored:
        icon = "✓" if s.accepted else "✗"
        style = "green" if s.accepted else "red"
        console.print(
            f"  [{style}]{icon}[/{style}] "
            f"[dim][{s.score.total_score:3d}][/dim] "
            f"{s.story.title[:70]} "
            f"[dim]({s.story.source_name})[/dim]"
        )
        if s.rejection_reasons:
            for reason in s.rejection_reasons[:2]:
                console.print(f"       [dim red]→ {reason}[/dim red]")

    accepted = sum(1 for s in scored if s.accepted)
    console.print(f"\n[bold]{accepted}/{len(scored)} stories accepted[/bold]")


@cli.command()
@click.option("--script", type=click.Path(exists=True), help="Path to script.json to render")
@click.pass_context
def render(ctx, script):
    """Render a video from an existing script file."""
    from src.pipeline import Pipeline

    if not script:
        console.print("[red]Please provide --script path[/red]")
        return

    console.print(f"\n[bold cyan]🎬 Rendering from script...[/bold cyan]\n")

    pipeline = Pipeline(config_path=ctx.obj["config_path"])

    script_path = Path(script)
    package_dir = script_path.parent

    # Check for voiceover
    audio_path = package_dir / "voiceover.mp3"
    if not audio_path.exists():
        console.print("[yellow]No voiceover found. Generating...[/yellow]")
        pipeline.regenerate_voice(str(package_dir))

    # Regenerate captions
    srt_path, ass_path = pipeline.regenerate_captions(str(package_dir))
    
    # Read script and metadata
    import json
    from src.models.schemas import GeneratedScript, VisualTemplate
    script_data = json.loads(script_path.read_text())
    script_obj = GeneratedScript(**script_data)
    
    metadata_path = package_dir / "metadata.json"
    accent_color = (0, 200, 255)
    template_type = VisualTemplate.DARK_GRADIENT
    
    if metadata_path.exists():
        meta_data = json.loads(metadata_path.read_text())
        # Try to extract template choices if they were saved in a previous run
        pass
        
    # Read captions
    from src.captions.formatter import CaptionFormatter
    
    word_timestamps = pipeline.aligner.align_audio(str(audio_path), script_obj.full_script)
    caption_lines = pipeline.caption_formatter.create_caption_lines(word_timestamps)
    
    audio_duration = pipeline._get_audio_duration(str(audio_path)) or script_obj.estimated_duration_seconds
    
    from src.video.smart_broll import SmartBRollAgent
    from src.models.schemas import RawStory
    # Create a mock raw story for the broll agent if none exists
    sources = script_obj.source_list
    url = sources[1] if len(sources) > 1 else "mock://url"
    story = RawStory(
        title=script_obj.title_ideas[0] if script_obj.title_ideas else "Demo",
        url=url,
        source_name=sources[0] if sources else "Demo Source",
        snippet="",
        published_at=None,
        categories=[]
    )
    console.print("[cyan]Acquiring B-Roll Media...[/cyan]")
    broll_agent = SmartBRollAgent(str(package_dir), pipeline.openai_client)
    media_paths = broll_agent.acquire_media(script_obj, story, accent_color)

    console.print("[cyan]Rendering video frames...[/cyan]")
    paths = pipeline.video_renderer.render(
        output_dir=str(package_dir),
        audio_path=str(audio_path),
        script=script_obj,
        caption_lines=caption_lines,
        media_paths=media_paths,
        total_duration=audio_duration,
        template_type=template_type,
        accent_color=accent_color,
        channel_name=pipeline.channel_name,
        source_name=script_obj.source_list[0] if script_obj.source_list else ""
    )

    console.print(f"[green]✓ Rendered to {package_dir}[/green]")
    console.print(f"  Video: {paths.get('video')}")


@cli.command()
@click.option("--package", "-p", type=click.Path(exists=True), help="Specific package directory")
@click.option("--voice", is_flag=True, help="Regenerate voiceover")
@click.option("--captions", is_flag=True, help="Regenerate captions")
@click.option("--metadata", is_flag=True, help="Regenerate metadata")
@click.pass_context
def regenerate(ctx, package, voice, captions, metadata):
    """Regenerate specific components of a package."""
    from src.pipeline import Pipeline

    if not package:
        console.print("[red]Please provide --package path[/red]")
        return

    pipeline = Pipeline(config_path=ctx.obj["config_path"])

    if voice:
        console.print("[cyan]Regenerating voiceover...[/cyan]")
        pipeline.regenerate_voice(package)
        console.print("[green]✓ Voiceover regenerated[/green]")

    if captions:
        console.print("[cyan]Regenerating captions...[/cyan]")
        pipeline.regenerate_captions(package)
        console.print("[green]✓ Captions regenerated[/green]")

    if metadata:
        console.print("[yellow]Metadata regeneration: use generate command with existing script[/yellow]")


@cli.command()
@click.option("--status", "-s", default=None, help="Filter by status (pending/approved/rejected)")
@click.option("--detail", "-d", default=None, help="Show detail for a specific package directory")
@click.option("--approve", type=click.Path(exists=True), help="Approve a package")
@click.option("--reject", type=click.Path(exists=True), help="Reject a package")
@click.pass_context
def review(ctx, status, detail, approve, reject):
    """Review output packages."""
    import yaml
    from src.models.schemas import ReviewStatus
    from src.review.reviewer import ReviewInterface

    config_path = ctx.obj["config_path"]
    config = {}
    if Path(config_path).exists():
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}

    output_folder = config.get("output", {}).get("folder", "./output")
    reviewer = ReviewInterface(output_folder)

    if approve:
        reviewer.set_review_status(approve, ReviewStatus.APPROVED)
        return

    if reject:
        reviewer.set_review_status(reject, ReviewStatus.REJECTED)
        return

    if detail:
        reviewer.show_package_detail(detail)
        return

    reviewer.show_summary_table(status_filter=status)


@cli.command()
@click.pass_context
def stats(ctx):
    """Show pipeline statistics."""
    from src.pipeline import Pipeline

    pipeline = Pipeline(config_path=ctx.obj["config_path"])
    stats = pipeline.get_stats()

    console.print("\n[bold cyan]📊 Pipeline Statistics[/bold cyan]\n")
    console.print(f"  Total stories discovered: {stats['total_stories']}")
    console.print(f"  Stories processed:        {stats['processed_stories']}")
    console.print(f"  Videos generated:         {stats['total_videos']}")
    console.print(f"  Unique hooks used:        {stats['total_hooks']}")


@cli.command()
@click.pass_context
def demo(ctx):
    """Run demo mode with mock data (no API calls needed)."""
    console.print("\n[bold cyan]🎭 Running Demo Mode[/bold cyan]\n")
    console.print("This generates a sample output package using mock data.\n")

    from src.models.schemas import (
        CaptionLine,
        GeneratedScript,
        OutputPackage,
        QualityCheck,
        QualityReport,
        QualityVerdict,
        RawStory,
        ScriptSection,
        ScriptStructureType,
        StoryScore,
        VideoMetadata,
        VisualCue,
        VoiceConfig,
        WordTimestamp,
    )

    # Mock story
    story = RawStory(
        title="Nvidia Announces Next-Gen Blackwell Ultra AI Chip With 2x Performance",
        url="https://example.com/nvidia-blackwell-ultra",
        source_name="TechCrunch",
        source_url="https://techcrunch.com",
        snippet="Nvidia unveiled its latest AI chip, the Blackwell Ultra B300, at GTC 2026. The chip promises 2x performance over the previous generation and targets enterprise AI training workloads. Major cloud providers including AWS, Google Cloud, and Azure have already committed to deploying the new chips.",
        published_at=None,
        categories=[],
    )

    # Mock score
    score = StoryScore(
        freshness=95,
        source_credibility=85,
        relevance=90,
        viral_potential=80,
        educational_value=85,
        business_angle=90,
        visual_potential=70,
        explainability=85,
    )

    # Mock script
    sections = ScriptSection(
        hook="Nvidia just dropped a chip that could change who wins the AI race.",
        main_explanation="At GTC 2026, Nvidia announced the Blackwell Ultra B300 — their fastest AI training chip ever. It delivers 2x the performance of the previous generation, and every major cloud provider is already onboard.",
        why_it_matters="This matters because faster chips mean faster AI development. Companies that get access first will ship products months ahead of competitors.",
        student_dev_angle="If you're a CS student, this is the hardware your future employer will be building on. Understanding GPU architecture is becoming a real career advantage.",
        closing_line="The AI chip war just got a lot more interesting. Nvidia is betting everything on being the picks and shovels of the AI gold rush.",
    )

    script = GeneratedScript(
        sections=sections,
        full_script=(
            f"{sections.hook} {sections.main_explanation} "
            f"{sections.why_it_matters} {sections.student_dev_angle} "
            f"{sections.closing_line}"
        ),
        word_count=108,
        estimated_duration_seconds=38,
        structure_type=ScriptStructureType.COMPANY_MOVE,
        visual_plan=[
            VisualCue(section="hook", description="Bold text: 'THE AI CHIP WAR'", text_overlay="THE AI CHIP WAR"),
            VisualCue(section="explanation", description="Nvidia logo + chip specs", text_overlay="Blackwell Ultra B300: 2x Performance"),
            VisualCue(section="why_it_matters", description="Timeline of AI chip releases", text_overlay="Faster Chips → Faster AI"),
            VisualCue(section="closing", description="Career takeaway", text_overlay="GPU knowledge = career advantage"),
        ],
        caption_lines=[
            "Nvidia just dropped a chip",
            "that could change",
            "who wins the AI race.",
            "At GTC 2026,",
            "Nvidia announced the",
            "Blackwell Ultra B300.",
            "Their fastest AI chip ever.",
            "2x the performance.",
            "Every major cloud provider",
            "is already onboard.",
            "This matters because",
            "faster chips mean",
            "faster AI development.",
            "If you're a CS student,",
            "GPU architecture is becoming",
            "a real career advantage.",
            "The AI chip war",
            "just got more interesting.",
        ],
        title_ideas=[
            "Nvidia Just Changed the AI Chip Game",
            "This Chip Could Decide Who Wins the AI Race",
            "Why CS Students Need to Watch Nvidia Right Now",
            "Blackwell Ultra: What It Means for AI Development",
        ],
        description="Nvidia announced the Blackwell Ultra B300 at GTC 2026 — a 2x performance leap for AI training. Here's why it matters for students and developers.",
        hashtags=["#Nvidia", "#AIChips", "#BlackwellUltra", "#GTC2026", "#AINews", "#TechShorts", "#ComputerScience", "#GPU"],
        source_list=["TechCrunch", "https://example.com/nvidia-blackwell-ultra"],
        commentary_notes="Added career angle for CS students, contextualized the chip within the broader AI race narrative, explained business implications.",
    )

    # Mock quality report
    quality = QualityReport(
        verdict=QualityVerdict.APPROVED,
        overall_score=85,
        checks=[
            QualityCheck(name="word_count", passed=True, score=90, reason="108 words, within 80-120 range"),
            QualityCheck(name="original_commentary", passed=True, score=90, reason="Has original career angle and business analysis"),
            QualityCheck(name="why_it_matters", passed=True, score=90, reason="Clear relevance section for students/devs"),
            QualityCheck(name="hook_strength", passed=True, score=82, reason="Strong opening with competitive framing"),
            QualityCheck(name="not_ai_slop", passed=True, score=88, reason="Feels authentic with specific details"),
            QualityCheck(name="sources_present", passed=True, score=90, reason="TechCrunch credited"),
        ],
        warnings=[],
        suggested_fixes=[],
        safe_to_post=True,
    )

    # Mock metadata
    metadata = VideoMetadata(
        title_options=script.title_ideas,
        description=script.description + "\n\n🤖 AI Disclosure: AI-generated narration and editing. Sources credited. Human reviewed.\n\n📰 Sources:\n• TechCrunch",
        hashtags=script.hashtags,
        source_links=[story.url],
        ai_disclosure="AI-generated narration (OpenAI tts-1-hd, voice: nova). AI-assisted editing. Sources credited.",
        recommended_platform="YouTube Shorts",
        review_warnings=[],
        manual_review_required=True,
    )

    # Mock voice config
    voice_config = VoiceConfig(voice="nova", model="tts-1-hd", speed=1.05)

    # Save demo package
    demo_dir = Path("./demo/example_output/2026-06-01_nvidia-blackwell-ultra-chip")
    demo_dir.mkdir(parents=True, exist_ok=True)

    (demo_dir / "script.json").write_text(json.dumps(script.model_dump(), indent=2, default=str))
    (demo_dir / "quality_report.json").write_text(json.dumps(quality.model_dump(), indent=2, default=str))

    meta_dict = metadata.model_dump()
    meta_dict["review_status"] = "pending"
    (demo_dir / "metadata.json").write_text(json.dumps(meta_dict, indent=2, default=str))

    (demo_dir / "sources.json").write_text(json.dumps({
        "story_url": story.url,
        "source_name": story.source_name,
        "sources": script.source_list,
        "ai_disclosure": metadata.ai_disclosure,
    }, indent=2))

    # Generate mock captions
    srt_content = ""
    for i, line in enumerate(script.caption_lines, 1):
        start_s = (i - 1) * 2.1
        end_s = start_s + 2.0
        srt_content += f"{i}\n{_fmt_srt(start_s)} --> {_fmt_srt(end_s)}\n{line}\n\n"
    (demo_dir / "captions.srt").write_text(srt_content)

    console.print("[green bold]✓ Demo package generated![/green bold]\n")
    console.print(f"  📦 Location: {demo_dir}")
    console.print(f"  📝 Script:   {demo_dir / 'script.json'}")
    console.print(f"  📊 Quality:  {demo_dir / 'quality_report.json'}")
    console.print(f"  📋 Metadata: {demo_dir / 'metadata.json'}")
    console.print(f"  📰 Sources:  {demo_dir / 'sources.json'}")
    console.print(f"  🎬 Captions: {demo_dir / 'captions.srt'}")

    console.print("\n[dim]Note: No video/audio rendered in demo mode (no API calls).[/dim]")
    console.print("[dim]Run 'python -m src.cli generate' with API keys for full pipeline.[/dim]")

    # Show review
    console.print("\n")
    from src.review.reviewer import ReviewInterface
    reviewer = ReviewInterface(str(demo_dir.parent))
    reviewer.show_package_detail(str(demo_dir))


def _fmt_srt(seconds: float) -> str:
    """Format seconds as SRT timestamp."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


@cli.command("check-deps")
def check_deps():
    """Check if all dependencies are installed correctly."""
    console.print("\n[bold cyan]🔍 Checking dependencies...[/bold cyan]\n")

    deps = {
        "openai": "OpenAI API client",
        "pydantic": "Data models",
        "click": "CLI framework",
        "yaml": "YAML config (pyyaml)",
        "dotenv": "Environment variables (python-dotenv)",
        "feedparser": "RSS feeds",
        "requests": "HTTP requests",
        "rapidfuzz": "Fuzzy matching",
        "PIL": "Image processing (Pillow)",
        "rich": "Rich terminal output",
        "slugify": "URL slugs (python-slugify)",
    }

    all_ok = True
    for module, description in deps.items():
        try:
            __import__(module)
            console.print(f"  [green]✓[/green] {description} ({module})")
        except ImportError:
            console.print(f"  [red]✗[/red] {description} ({module}) — NOT INSTALLED")
            all_ok = False

    # Check FFmpeg
    import subprocess
    try:
        result = subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
        version = result.stdout.decode().split("\n")[0] if result.returncode == 0 else "unknown"
        console.print(f"  [green]✓[/green] FFmpeg ({version[:50]})")
    except FileNotFoundError:
        console.print(f"  [red]✗[/red] FFmpeg — NOT INSTALLED (brew install ffmpeg)")
        all_ok = False

    # Check ffprobe
    try:
        subprocess.run(["ffprobe", "-version"], capture_output=True, timeout=5)
        console.print(f"  [green]✓[/green] ffprobe")
    except FileNotFoundError:
        console.print(f"  [red]✗[/red] ffprobe — NOT INSTALLED (comes with ffmpeg)")
        all_ok = False

    # Optional: Whisper
    try:
        import whisper_timestamped
        console.print(f"  [green]✓[/green] whisper-timestamped (word-level captions)")
    except ImportError:
        console.print(f"  [yellow]⚠[/yellow] whisper-timestamped — NOT INSTALLED (optional, will use estimated timestamps)")

    # Check API keys
    console.print("\n[bold]API Keys:[/bold]")
    import os
    from dotenv import load_dotenv
    load_dotenv()

    if os.getenv("OPENAI_API_KEY"):
        console.print(f"  [green]✓[/green] OPENAI_API_KEY set")
    else:
        console.print(f"  [red]✗[/red] OPENAI_API_KEY not set")
        all_ok = False

    if os.getenv("NEWSDATA_API_KEY"):
        console.print(f"  [green]✓[/green] NEWSDATA_API_KEY set")
    else:
        console.print(f"  [yellow]⚠[/yellow] NEWSDATA_API_KEY not set (will use RSS fallback)")

    if all_ok:
        console.print("\n[green bold]✓ All required dependencies are installed![/green bold]")
    else:
        console.print("\n[red bold]✗ Some dependencies are missing. Run: pip install -r requirements.txt[/red bold]")


def main():
    cli(obj={})


if __name__ == "__main__":
    main()
