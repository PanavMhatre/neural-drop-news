# AI + Tech News Shorts Production System

An automated pipeline that discovers AI/tech news, scores stories, generates original scripts with commentary, produces AI voiceover, renders vertical videos with animated captions, and packages everything for manual review before posting.

**This is NOT a bot that reads articles.** Every video includes original commentary, source crediting, and a "why this matters" angle. Manual review is required before posting.

---

## What It Does

```
News Sources → Discover → Score → Dedup → Script → Quality Gate → Voice → Captions → Video → Package
                                                        ↑                                       ↓
                                                   Retry with                            Manual Review
                                                   feedback
```

1. **Discovers** fresh AI/tech news from NewsData.io + RSS feeds
2. **Scores** each story (0-100) on freshness, credibility, relevance, viral potential, etc.
3. **Deduplicates** against past stories, hooks, structures, and templates
4. **Generates** original scripts with GPT-4o (structured output, enforced commentary)
5. **Quality-checks** scripts for originality, commentary, claims, and "AI slop"
6. **Creates** AI voiceover with OpenAI TTS (tone-matched voice selection)
7. **Aligns** word-level captions using Whisper
8. **Renders** 9:16 vertical videos with animated text, progress bars, and source credits
9. **Packages** everything into a review-ready folder

---

## Quick Start

### 1. Prerequisites

- **Python 3.11+**
- **FFmpeg** (for video rendering)
- **OpenAI API key** (for GPT-4o, TTS, Whisper)
- **NewsData.io API key** (optional, free tier, for news discovery)

```bash
# Install FFmpeg (macOS)
brew install ffmpeg

# Install FFmpeg (Ubuntu/Debian)
sudo apt install ffmpeg
```

### 2. Setup

```bash
cd News

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Set up API keys
cp .env.example .env
# Edit .env with your keys:
#   OPENAI_API_KEY=sk-your-key-here
#   NEWSDATA_API_KEY=your-newsdata-key-here (optional)

# Check everything is installed
python -m src.cli check-deps
```

### 3. Run Demo (No API Keys Needed)

```bash
python -m src.cli demo
```

This creates a sample output package with mock data so you can see the full output structure.

### 4. Generate One Video

```bash
python -m src.cli generate --count 1
```

### 5. Generate from a Specific Topic

```bash
python -m src.cli generate --topic "OpenAI GPT-5 release" --count 1
```

---

## Commands

| Command | Description | Example |
|:--------|:------------|:--------|
| `generate` | Full pipeline: discover → score → script → voice → render → package | `python -m src.cli generate --count 3` |
| `discover` | Find and score stories (no rendering) | `python -m src.cli discover --count 10` |
| `render` | Render video from existing script | `python -m src.cli render --script ./output/pkg/script.json` |
| `regenerate` | Redo voiceover, captions, or metadata | `python -m src.cli regenerate --package ./output/pkg --voice` |
| `review` | Review all output packages | `python -m src.cli review` |
| `review --detail` | Detailed view of one package | `python -m src.cli review --detail ./output/pkg` |
| `review --approve` | Approve a package | `python -m src.cli review --approve ./output/pkg` |
| `stats` | Show pipeline statistics | `python -m src.cli stats` |
| `demo` | Generate sample output with mock data | `python -m src.cli demo` |
| `check-deps` | Verify all dependencies are installed | `python -m src.cli check-deps` |

### Global Options

```bash
python -m src.cli --config custom_config.yaml generate --count 3
python -m src.cli -v generate --count 1   # Verbose/debug mode
```

---

## Output Package Structure

Each video is saved in its own folder under `./output/`:

```
output/2026-06-01_nvidia-blackwell-ultra-chip/
├── video.mp4           # Final 9:16 vertical video
├── voiceover.mp3       # AI-generated narration
├── script.json         # Full script with sections
├── captions.srt        # Caption file (standard format)
├── captions.ass        # Styled caption file (for burn-in)
├── metadata.json       # Title options, description, hashtags, AI disclosure
├── sources.json        # Source URLs and crediting info
├── quality_report.json # Quality gate results and scores
└── thumbnail.png       # Opening frame image
```

---

## Configuration

All settings are in `config.yaml`. Key options:

```yaml
channel:
  name: "TechPulse Shorts"        # Channel branding
  daily_video_limit: 5             # Max videos per day

discovery:
  provider: "newsdata"             # "newsdata", "rss", or "both"
  max_age_hours: 48                # Reject stories older than this

scoring:
  minimum_score: 55                # Stories below this are rejected

scripts:
  target_word_count_min: 80        # Script length bounds
  target_word_count_max: 120
  llm_temperature: 0.8            # Creativity level

voice:
  default_voice: "nova"            # OpenAI TTS voice
  speed: 1.05                     # Narration speed

quality:
  strictness: "medium"            # "low", "medium", "high"

output:
  render_video: true               # false = generate scripts only
```

See the full `config.yaml` for all options.

---

## API Keys Needed

| Key | Required | Free Tier | What It's For |
|:----|:---------|:----------|:--------------|
| `OPENAI_API_KEY` | **Yes** | Pay-as-you-go | GPT-4o (scripts, scoring, quality), TTS (voice), Whisper (captions) |
| `NEWSDATA_API_KEY` | Optional | 200 credits/day | News discovery (falls back to RSS if not set) |

**Cost per video:** ~$0.05–$0.15 (GPT-4o + TTS)

---

## How to Review Outputs

1. **List all packages:**
   ```bash
   python -m src.cli review
   ```

2. **View details of a specific package:**
   ```bash
   python -m src.cli review --detail ./output/2026-06-01_nvidia-blackwell-ultra-chip
   ```

3. **Approve or reject:**
   ```bash
   python -m src.cli review --approve ./output/2026-06-01_nvidia-blackwell-ultra-chip
   python -m src.cli review --reject ./output/2026-06-01_nvidia-blackwell-ultra-chip
   ```

### What to Check Before Posting

- ✅ Script is accurate (facts match sources)
- ✅ No exaggerated or misleading claims
- ✅ Sources are properly credited
- ✅ AI disclosure is present in description
- ✅ Title is curiosity-driven but not fake
- ✅ Video looks good and captions are readable
- ✅ No copyrighted material
- ✅ Different structure/visual from recent videos

---

## How It Avoids Low-Quality Content

YouTube penalizes mass-produced, repetitive content. This system prevents that through:

1. **Original commentary** — GPT-4o is instructed to add analysis, not summarize
2. **Quality gate** — Rejects scripts that are "just summaries" or "AI slop"
3. **Source crediting** — Always credits the original publication
4. **Structure rotation** — 7 different script formats, automatically rotated
5. **Template rotation** — 4 visual templates with 6 accent colors, never repeating
6. **Hook tracking** — Prevents similar opening lines across videos
7. **Deduplication** — Fuzzy title matching prevents near-duplicate stories
8. **AI disclosure** — Every video includes a disclosure in the description
9. **Manual review** — Nothing is auto-posted; human approval required

---

## Why Manual Review Is Required

AI-generated content needs human oversight because:

- **Facts can be wrong** — LLMs can hallucinate or misinterpret sources
- **Context can be missing** — Short scripts may oversimplify complex topics
- **Tone can be off** — What reads well may not watch well
- **Sources may be outdated** — News moves fast; verify before posting
- **Platform rules evolve** — YouTube's monetization policies change
- **Quality standards** — Your channel reputation depends on every video

**Do not auto-post.** Always watch the video, read the script, and verify sources before publishing.

---

## Architecture

```
src/
├── cli.py              # Click CLI commands
├── pipeline.py         # Main orchestrator
├── discovery/          # News sources (NewsData, RSS)
├── scoring/            # GPT-4o story scoring
├── memory/             # SQLite dedup + usage tracking
├── scripts/            # Script generation + quality gate
├── voice/              # OpenAI TTS
├── captions/           # Whisper alignment + SRT/ASS export
├── video/              # Pillow frame rendering + FFmpeg encoding
├── metadata/           # Title/description/hashtag generation
├── review/             # CLI review interface
└── models/             # Pydantic data models
```

---

## Troubleshooting

| Problem | Solution |
|:--------|:---------|
| `OPENAI_API_KEY not found` | Copy `.env.example` to `.env` and add your key |
| `FFmpeg not found` | Install: `brew install ffmpeg` (macOS) |
| `No stories discovered` | Check if NewsData API key is set, or use `--topic` |
| `All stories rejected` | Lower `scoring.minimum_score` in `config.yaml` |
| `Script quality too low` | Lower `quality.strictness` or increase `scripts.max_retries` |
| `Font not found` | System fonts are used as fallback; or download Inter font |
| `Video renders slowly` | Lower `video.fps` to 24 or `video.quality` to "low" |
| `Whisper not installed` | Estimated timestamps are used automatically as fallback |

---

## License

Private project. Not for redistribution.
