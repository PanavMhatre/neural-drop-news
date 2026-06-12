"""Re-render the last video to test karaoke captions."""
import json, sys, os
sys.path.insert(0, ".")

from src.video.compositor import FrameCompositor
from src.video.templates import get_template
from src.models.schemas import GeneratedScript, CaptionLine, WordTimestamp, VisualTemplate
from src.captions.formatter import CaptionFormatter  # noqa
import glob

output_dir = "output/2026-06-11_xrp-price-support-in-focus-transaction-demand-fal"

with open(f"{output_dir}/script.json") as f:
    script = GeneratedScript(**json.load(f))

with open(f"{output_dir}/metadata.json") as f:
    meta = json.load(f)

# Load captions with word timing (they're stored from Whisper)
def parse_srt(path):
    import re
    captions = []
    with open(path) as f:
        blocks = f.read().strip().split("\n\n")
    time_re = re.compile(r"(\d+):(\d+):(\d+),(\d+) --> (\d+):(\d+):(\d+),(\d+)")
    for block in blocks:
        lines = block.strip().splitlines()
        if len(lines) < 3:
            continue
        m = time_re.match(lines[1])
        if not m:
            continue
        def ts(*parts):
            h, m2, s, ms = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
            return h*3600 + m2*60 + s + ms/1000
        start = ts(*m.groups()[:4])
        end = ts(*m.groups()[4:])
        text = " ".join(lines[2:])
        captions.append(CaptionLine(text=text, start_time=start, end_time=end))
    return captions

captions = parse_srt(f"{output_dir}/captions.srt")

audio_path = f"{output_dir}/voiceover.mp3"

# Gather media
media_paths = {}
media_dir = f"{output_dir}/media"
if os.path.exists(media_dir):
    for f in os.listdir(media_dir):
        key = os.path.splitext(f)[0]
        media_paths[key] = os.path.join(media_dir, f)

import yaml
with open("config.yaml") as f:
    cfg = yaml.safe_load(f)

vcfg = cfg["video"]
comp = FrameCompositor(vcfg["width"], vcfg["height"], vcfg["fps"])

template = get_template(VisualTemplate.DARK_GRADIENT)
template.hook_font_size = vcfg.get("hook_font_size", 80)
template.body_font_size = vcfg.get("body_font_size", 52)
template.caption_font_size = vcfg.get("caption_font_size", 60)

total_dur = meta.get("duration", 36.0)
accent = tuple(vcfg["accent_colors"][0])

print("Rendering with karaoke captions...")
comp.render_video(
    output_path=f"{output_dir}/video_karaoke.mp4",
    audio_path=audio_path,
    template=template,
    accent_color=accent,
    script=script,
    caption_lines=captions,
    media_paths=media_paths,
    total_duration=total_dur,
    channel_name="Neural Drop",
    source_text="",
    show_progress_bar=True,
)
print(f"Done -> {output_dir}/video_karaoke.mp4")
