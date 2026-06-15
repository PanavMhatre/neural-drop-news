import base64
import json
import mimetypes
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import requests


DISCORD_LIMIT_BYTES = 25 * 1024 * 1024
GITHUB_API_URL = "https://api.github.com"


class PublicMediaError(RuntimeError):
    pass


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _save_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n")


def _github_token() -> str:
    token = os.getenv("STORAGE_TOKEN") or os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if token:
        return token

    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (subprocess.SubprocessError, FileNotFoundError) as exc:
        raise PublicMediaError("GitHub token is not configured and gh auth token failed") from exc

    token = result.stdout.strip()
    if not token:
        raise PublicMediaError("GitHub token is not configured")
    return token


def _github_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_github_token()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _ensure_github_branch(repo: str, branch: str) -> None:
    headers = _github_headers()
    branch_url = f"{GITHUB_API_URL}/repos/{repo}/git/ref/heads/{branch}"
    response = requests.get(branch_url, headers=headers, timeout=30)
    if response.status_code == 200:
        return
    if response.status_code not in (404, 409):
        raise PublicMediaError(f"GitHub branch check failed with HTTP {response.status_code}")

    # Use Contents API — works on empty repos where the git data API returns 409.
    init_response = requests.put(
        f"{GITHUB_API_URL}/repos/{repo}/contents/README.md",
        headers=headers,
        json={
            "message": "Initialize storage",
            "content": base64.b64encode(b"# NeuralDropBits storage\n").decode(),
            "branch": branch,
        },
        timeout=30,
    )
    if init_response.status_code not in (200, 201):
        raise PublicMediaError(f"GitHub storage init failed with HTTP {init_response.status_code}")


def upload_to_discord(path: Path) -> str:
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        raise PublicMediaError("DISCORD_WEBHOOK_URL is not configured")

    with path.open("rb") as file_obj:
        response = requests.post(
            webhook_url,
            data={"payload_json": json.dumps({"content": f"NeuralDropBits media: {path.name}"})},
            files={"file": (path.name, file_obj, mimetypes.guess_type(path.name)[0] or "application/octet-stream")},
            timeout=120,
        )
    if response.status_code >= 400:
        raise PublicMediaError(f"Discord upload failed with HTTP {response.status_code}")

    payload = response.json()
    attachments = payload.get("attachments") or []
    if not attachments or not attachments[0].get("url"):
        raise PublicMediaError("Discord upload did not return an attachment URL")
    return attachments[0]["url"]


GITHUB_RELEASE_TAG = "media-store"


def _get_or_create_release(repo: str, headers: dict) -> dict:
    """Return the persistent media-store release, creating it if needed."""
    resp = requests.get(
        f"{GITHUB_API_URL}/repos/{repo}/releases/tags/{GITHUB_RELEASE_TAG}",
        headers=headers,
        timeout=30,
    )
    if resp.status_code == 200:
        return resp.json()
    release_resp = requests.post(
        f"{GITHUB_API_URL}/repos/{repo}/releases",
        headers=headers,
        json={
            "tag_name": GITHUB_RELEASE_TAG,
            "name": "Media Store",
            "body": "Automated media assets",
            "draft": False,
            "prerelease": False,
        },
        timeout=30,
    )
    if release_resp.status_code >= 400:
        raise PublicMediaError(f"GitHub release creation failed with HTTP {release_resp.status_code}")
    return release_resp.json()


def _upload_release_asset(repo: str, headers: dict, release: dict, path: Path, asset_name: str) -> str:
    """Upload a file as a release asset, deleting any existing asset with the same name first."""
    for existing in release.get("assets", []):
        if existing["name"] == asset_name:
            requests.delete(
                f"{GITHUB_API_URL}/repos/{repo}/releases/assets/{existing['id']}",
                headers=headers,
                timeout=30,
            )
            break

    upload_url = release["upload_url"].split("{")[0]
    upload_headers = {**headers, "Content-Type": "application/octet-stream"}
    with path.open("rb") as fh:
        resp = requests.post(
            upload_url,
            headers=upload_headers,
            params={"name": asset_name},
            data=fh,
            timeout=300,
        )
    if resp.status_code >= 400:
        raise PublicMediaError(f"GitHub release asset upload failed with HTTP {resp.status_code}")
    return resp.json()["browser_download_url"]


def upload_to_github_storage(path: Path, package_id: str) -> str:
    repo = os.getenv("STORAGE_REPO") or os.getenv("GITHUB_STORAGE_REPO", "panavm12-jpg/storage")
    branch = os.getenv("STORAGE_BRANCH") or os.getenv("GITHUB_STORAGE_BRANCH", "main")
    headers = _github_headers()

    # Always use a GitHub Release asset — the Contents API rejects files
    # well below its documented 100 MB limit in practice.
    _ensure_github_branch(repo, branch)
    release = _get_or_create_release(repo, headers)
    asset_name = f"{package_id}__{path.name}"
    return _upload_release_asset(repo, headers, release, path, asset_name)


def upload_public_asset(path: Path, package_id: str) -> tuple[str, str]:
    return upload_to_github_storage(path, package_id), "github"


def public_assets_for_package(package_dir: Path) -> dict:
    manifest_path = package_dir / "public_media.json"
    manifest = _load_json(manifest_path)
    package_id = package_dir.name
    assets = manifest.setdefault("assets", {})

    for filename in ("video.mp4", "thumbnail.png"):
        file_path = package_dir / filename
        if not file_path.exists():
            continue

        size = file_path.stat().st_size
        existing = assets.get(filename)
        if existing and existing.get("size") == size and existing.get("url"):
            continue

        url, provider = upload_public_asset(file_path, package_id)
        assets[filename] = {
            "url": url,
            "provider": provider,
            "size": size,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
        }

    _save_json(manifest_path, manifest)
    return manifest
