import base64
import json
import mimetypes
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

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

    commit_response = requests.post(
        f"{GITHUB_API_URL}/repos/{repo}/git/blobs",
        headers=headers,
        json={"content": "# NeuralDropBits storage\n", "encoding": "utf-8"},
        timeout=30,
    )
    if commit_response.status_code >= 400:
        raise PublicMediaError(f"GitHub blob creation failed with HTTP {commit_response.status_code}")
    blob_sha = commit_response.json()["sha"]

    tree_response = requests.post(
        f"{GITHUB_API_URL}/repos/{repo}/git/trees",
        headers=headers,
        json={"tree": [{"path": "README.md", "mode": "100644", "type": "blob", "sha": blob_sha}]},
        timeout=30,
    )
    if tree_response.status_code >= 400:
        raise PublicMediaError(f"GitHub tree creation failed with HTTP {tree_response.status_code}")
    tree_sha = tree_response.json()["sha"]

    new_commit_response = requests.post(
        f"{GITHUB_API_URL}/repos/{repo}/git/commits",
        headers=headers,
        json={"message": "Initialize storage", "tree": tree_sha},
        timeout=30,
    )
    if new_commit_response.status_code >= 400:
        raise PublicMediaError(f"GitHub commit creation failed with HTTP {new_commit_response.status_code}")
    commit_sha = new_commit_response.json()["sha"]

    ref_response = requests.post(
        f"{GITHUB_API_URL}/repos/{repo}/git/refs",
        headers=headers,
        json={"ref": f"refs/heads/{branch}", "sha": commit_sha},
        timeout=30,
    )
    if ref_response.status_code >= 400:
        raise PublicMediaError(f"GitHub branch creation failed with HTTP {ref_response.status_code}")


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


def upload_to_github_storage(path: Path, package_id: str) -> str:
    repo = os.getenv("STORAGE_REPO") or os.getenv("GITHUB_STORAGE_REPO", "panavm12-jpg/storage")
    branch = os.getenv("STORAGE_BRANCH") or os.getenv("GITHUB_STORAGE_BRANCH", "main")
    prefix = os.getenv("GITHUB_STORAGE_PREFIX", "news")
    _ensure_github_branch(repo, branch)

    repo_path = f"{prefix.strip('/')}/{package_id}/{path.name}"
    encoded_path = quote(repo_path)
    content_url = f"{GITHUB_API_URL}/repos/{repo}/contents/{encoded_path}"
    headers = _github_headers()

    existing_response = requests.get(
        content_url,
        headers=headers,
        params={"ref": branch},
        timeout=30,
    )
    existing_sha = existing_response.json().get("sha") if existing_response.status_code == 200 else None

    payload = {
        "message": f"Add {package_id} {path.name}",
        "content": base64.b64encode(path.read_bytes()).decode("ascii"),
        "branch": branch,
    }
    if existing_sha:
        payload["sha"] = existing_sha

    response = requests.put(content_url, headers=headers, json=payload, timeout=180)
    if response.status_code >= 400:
        raise PublicMediaError(f"GitHub storage upload failed with HTTP {response.status_code}: {response.text[:200]}")

    return f"https://raw.githubusercontent.com/{repo}/{branch}/{quote(repo_path)}"


def upload_public_asset(path: Path, package_id: str) -> tuple[str, str]:
    if path.stat().st_size > DISCORD_LIMIT_BYTES:
        return upload_to_github_storage(path, package_id), "github"
    return upload_to_discord(path), "discord"


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
