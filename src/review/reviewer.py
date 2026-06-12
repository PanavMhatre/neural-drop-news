"""
CLI review interface for manual content review.

Displays output packages in a readable format for the human reviewer
to approve, reject, or flag for editing before posting.
"""

import json
import logging
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from src.models.schemas import OutputPackage, ReviewStatus

logger = logging.getLogger(__name__)
console = Console()


class ReviewInterface:
    """CLI-based review interface for video packages."""

    def __init__(self, output_folder: str = "./output"):
        self.output_folder = Path(output_folder)

    def list_packages(self, status_filter: Optional[str] = None) -> list[dict]:
        """
        List all output packages with summary info.

        Args:
            status_filter: Filter by review status (pending, approved, rejected).

        Returns:
            List of package summary dicts.
        """
        packages = []

        if not self.output_folder.exists():
            console.print("[yellow]No output folder found.[/yellow]")
            return packages

        for pkg_dir in sorted(self.output_folder.iterdir()):
            if not pkg_dir.is_dir():
                continue

            metadata_path = pkg_dir / "metadata.json"
            quality_path = pkg_dir / "quality_report.json"
            script_path = pkg_dir / "script.json"

            if not metadata_path.exists():
                continue

            try:
                metadata = json.loads(metadata_path.read_text())
                quality = json.loads(quality_path.read_text()) if quality_path.exists() else {}
                script = json.loads(script_path.read_text()) if script_path.exists() else {}

                review_status = metadata.get("review_status", "pending")

                if status_filter and review_status != status_filter:
                    continue

                packages.append({
                    "dir": str(pkg_dir),
                    "name": pkg_dir.name,
                    "title": metadata.get("title_options", ["Untitled"])[0],
                    "score": quality.get("overall_score", "?"),
                    "verdict": quality.get("verdict", "?"),
                    "status": review_status,
                    "warnings": metadata.get("review_warnings", []),
                    "has_video": (pkg_dir / "video.mp4").exists(),
                })
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"Failed to read package {pkg_dir.name}: {e}")
                continue

        return packages

    def show_summary_table(self, status_filter: Optional[str] = None) -> None:
        """Display a summary table of all packages."""
        packages = self.list_packages(status_filter)

        if not packages:
            console.print("[yellow]No packages found.[/yellow]")
            return

        table = Table(title="📦 Video Packages", show_lines=True)
        table.add_column("#", style="dim", width=4)
        table.add_column("Package", style="cyan", max_width=35)
        table.add_column("Title", max_width=40)
        table.add_column("Score", justify="center", width=7)
        table.add_column("Quality", justify="center", width=12)
        table.add_column("Status", justify="center", width=10)
        table.add_column("Video", justify="center", width=6)
        table.add_column("Warnings", max_width=25)

        for i, pkg in enumerate(packages, 1):
            score_style = "green" if pkg["score"] != "?" and int(pkg["score"]) >= 70 else "yellow"
            status_style = {
                "pending": "yellow",
                "approved": "green",
                "rejected": "red",
                "needs_edit": "magenta",
            }.get(pkg["status"], "white")

            warnings = ", ".join(pkg["warnings"][:2]) if pkg["warnings"] else "—"

            table.add_row(
                str(i),
                pkg["name"],
                pkg["title"][:40],
                f"[{score_style}]{pkg['score']}[/{score_style}]",
                pkg["verdict"],
                f"[{status_style}]{pkg['status']}[/{status_style}]",
                "✓" if pkg["has_video"] else "✗",
                warnings[:25],
            )

        console.print(table)

    def show_package_detail(self, package_dir: str) -> None:
        """Display detailed information about a single package."""
        pkg_dir = Path(package_dir)

        if not pkg_dir.exists():
            console.print(f"[red]Package not found: {package_dir}[/red]")
            return

        # Load files
        metadata = self._load_json(pkg_dir / "metadata.json")
        quality = self._load_json(pkg_dir / "quality_report.json")
        script = self._load_json(pkg_dir / "script.json")
        sources = self._load_json(pkg_dir / "sources.json")

        # Title options
        console.print(Panel(
            "\n".join(f"  {i}. {t}" for i, t in enumerate(metadata.get("title_options", []), 1)),
            title="🎬 Title Options",
            border_style="cyan",
        ))

        # Script
        if script:
            script_text = script.get("full_script", "N/A")
            console.print(Panel(
                script_text,
                title=f"📝 Script ({script.get('word_count', '?')} words, ~{script.get('estimated_duration_seconds', '?')}s)",
                border_style="green",
            ))

        # Quality Report
        if quality:
            quality_text = f"Verdict: {quality.get('verdict', '?')}\n"
            quality_text += f"Score: {quality.get('overall_score', '?')}/100\n\n"

            checks = quality.get("checks", [])
            for check in checks:
                icon = "✓" if check.get("passed") else "✗"
                quality_text += f"  {icon} {check.get('name', '?')}: {check.get('reason', '')}\n"

            if quality.get("warnings"):
                quality_text += "\n⚠️ Warnings:\n"
                for w in quality["warnings"]:
                    quality_text += f"  • {w}\n"

            if quality.get("suggested_fixes"):
                quality_text += "\n🔧 Suggested Fixes:\n"
                for f in quality["suggested_fixes"]:
                    quality_text += f"  • {f}\n"

            console.print(Panel(quality_text, title="📊 Quality Report", border_style="yellow"))

        # Sources
        if sources:
            source_text = "\n".join(f"  • {s}" for s in sources.get("sources", []))
            console.print(Panel(source_text, title="📰 Sources", border_style="blue"))

        # Metadata
        console.print(Panel(
            f"Description: {metadata.get('description', 'N/A')[:200]}\n"
            f"Hashtags: {' '.join(metadata.get('hashtags', []))}\n"
            f"Platform: {metadata.get('recommended_platform', 'N/A')}\n"
            f"AI Disclosure: {metadata.get('ai_disclosure', 'N/A')[:100]}...",
            title="📋 Metadata",
            border_style="magenta",
        ))

        # File paths
        files_text = ""
        for fname in ["video.mp4", "voiceover.mp3", "captions.srt", "captions.ass", "thumbnail.png"]:
            fpath = pkg_dir / fname
            status = "✓" if fpath.exists() else "✗"
            files_text += f"  {status} {fname}\n"

        console.print(Panel(files_text, title="📁 Files", border_style="dim"))

        # Warnings
        warnings = metadata.get("review_warnings", [])
        if warnings:
            console.print(Panel(
                "\n".join(f"  ⚠️ {w}" for w in warnings),
                title="⚠️ Review Warnings",
                border_style="red",
            ))

        # Safe to post?
        safe = quality.get("safe_to_post", False)
        if safe:
            console.print("[green bold]✓ Safe to post (quality gate passed, no warnings)[/green bold]")
        else:
            console.print("[yellow bold]⚠ Manual review required before posting[/yellow bold]")

    def set_review_status(
        self, package_dir: str, status: ReviewStatus, notes: Optional[str] = None
    ) -> None:
        """Update the review status of a package."""
        pkg_dir = Path(package_dir)
        metadata_path = pkg_dir / "metadata.json"

        if not metadata_path.exists():
            console.print(f"[red]Metadata not found: {metadata_path}[/red]")
            return

        metadata = json.loads(metadata_path.read_text())
        metadata["review_status"] = status.value
        if notes:
            metadata["review_notes"] = notes

        metadata_path.write_text(json.dumps(metadata, indent=2, default=str))
        console.print(f"[green]Updated {pkg_dir.name} → {status.value}[/green]")

    def _load_json(self, path: Path) -> dict:
        """Load a JSON file, returning empty dict on failure."""
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, IOError):
            return {}
