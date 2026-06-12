import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests


BUFFER_API_URL = "https://api.buffer.com"
CHANNEL_CTA_LINES = [
    "Full AI briefing in bio -> Neural Drop",
    "Get the 3-minute AI briefing -> bit.ly/neural-drop",
]
DEFAULT_YOUTUBE_CATEGORY = os.getenv("BUFFER_YOUTUBE_CATEGORY", "28")
BUFFER_SERVICE_ALIASES = {
    "x": "twitter",
    "twitter": "twitter",
    "instagram": "instagram",
    "tiktok": "tiktok",
    "youtube": "youtube",
    "facebook": "facebook",
    "linkedin": "linkedin",
    "threads": "threads",
    "bluesky": "bluesky",
    "mastodon": "mastodon",
    "pinterest": "pinterest",
    "google": "google",
    "googlebusiness": "google",
    "google_business": "google",
    "googlebusinessprofile": "google",
    "google_business_profile": "google",
    "startpage": "startpage",
    "start_page": "startpage",
}
BUFFER_SERVICE_ORDER = {
    "instagram": 0,
    "tiktok": 1,
    "youtube": 2,
    "twitter": 3,
    "threads": 4,
    "facebook": 5,
    "linkedin": 6,
    "bluesky": 7,
    "mastodon": 8,
    "pinterest": 9,
    "google": 10,
    "startpage": 11,
}


class BufferError(RuntimeError):
    pass


def normalize_due_at(value: str) -> str:
    scheduled = datetime.fromisoformat(value)
    if scheduled.tzinfo is None:
        scheduled = scheduled.astimezone()
    return scheduled.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def is_public_url(url: str) -> bool:
    lower = url.lower()
    return (
        lower.startswith("https://")
        and "localhost" not in lower
        and "127.0.0.1" not in lower
        and "::1" not in lower
    )


def canonical_buffer_service(service: str | None) -> str:
    return BUFFER_SERVICE_ALIASES.get(str(service or "").strip().casefold(), str(service or "").strip().casefold())


class BufferClient:
    def __init__(self, api_key: str | None = None, profile_name: str | None = None):
        self.api_key = api_key or os.getenv("BUFFER_API_KEY")
        self.profile_name = profile_name or os.getenv("BUFFER_PROFILE_NAME", "NeuralDropBits")
        if not self.api_key:
            raise BufferError("BUFFER_API_KEY is not configured")

    def _configured_channel_ids(self) -> set[str]:
        raw_ids = os.getenv("BUFFER_CHANNEL_IDS", "")
        return {channel_id.strip() for channel_id in raw_ids.split(",") if channel_id.strip()}

    def _graphql(self, query: str) -> dict:
        response = requests.post(
            BUFFER_API_URL,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={"query": query},
            timeout=30,
        )
        if response.status_code >= 400:
            raise BufferError(f"Buffer API returned HTTP {response.status_code}: {response.text}")

        payload = response.json()
        if payload.get("errors"):
            messages = "; ".join(error.get("message", "Unknown Buffer error") for error in payload["errors"])
            raise BufferError(messages)
        return payload.get("data", {})

    def list_organizations(self) -> list[dict]:
        data = self._graphql(
            """
            query GetOrganizations {
              account {
                organizations {
                  id
                  name
                  ownerEmail
                }
              }
            }
            """
        )
        return data.get("account", {}).get("organizations", [])

    def list_channels(self, organization_id: str) -> list[dict]:
        org_id = json.dumps(organization_id)
        data = self._graphql(
            f"""
            query GetChannels {{
              channels(input: {{ organizationId: {org_id} }}) {{
                id
                name
                displayName
                service
                isQueuePaused
              }}
            }}
            """
        )
        return data.get("channels", [])

    def resolve_target_channels(self) -> list[dict]:
        matches: list[dict] = []
        configured_ids = self._configured_channel_ids()
        seen_configured_ids: set[str] = set()
        target = self.profile_name.casefold()
        for organization in self.list_organizations():
            for channel in self.list_channels(organization["id"]):
                names = [
                    str(channel.get("name") or ""),
                    str(channel.get("displayName") or ""),
                ]
                exact_name_match = any(name.casefold() == target for name in names)
                channel_id = str(channel.get("id") or "")

                if configured_ids and channel_id in configured_ids:
                    if not exact_name_match:
                        raise BufferError(
                            f'Configured Buffer channel "{channel_id}" is not "{self.profile_name}"'
                        )
                    seen_configured_ids.add(channel_id)
                    matches.append({**channel, "organizationId": organization["id"]})
                elif not configured_ids and exact_name_match:
                    matches.append({**channel, "organizationId": organization["id"]})

        if configured_ids and seen_configured_ids != configured_ids:
            missing = ", ".join(sorted(configured_ids - seen_configured_ids))
            raise BufferError(f"Configured Buffer channel IDs were not found: {missing}")
        if not matches:
            raise BufferError(f'Buffer channel "{self.profile_name}" was not found')

        matches.sort(
            key=lambda channel: (
                BUFFER_SERVICE_ORDER.get(canonical_buffer_service(channel.get("service")), 99),
                str(channel.get("id") or ""),
            )
        )
        return matches

    def _create_scheduled_video_post_for_channel(
        self,
        channel: dict,
        text: str,
        due_at: str,
        video_url: str,
        thumbnail_url: str | None = None,
    ) -> dict:
        if not is_public_url(video_url):
            raise BufferError("Buffer video URL must be public HTTPS, not localhost or a local file")

        due_at_utc = normalize_due_at(due_at)
        video_asset = f"url: {json.dumps(video_url)}"
        service = canonical_buffer_service(channel.get("service"))
        if service == "instagram":
            extra_input = "metadata: { instagram: { type: reel, shouldShareToFeed: true } }"
        elif service == "youtube":
            title = text.split("\n")[0][:95] if text else "Tech News Short"
            extra_input = (
                "metadata: { youtube: { "
                f"title: {json.dumps(title)}, "
                f"categoryId: {json.dumps(DEFAULT_YOUTUBE_CATEGORY)}, "
                "isShort: true"
                " } }"
            )
        else:
            extra_input = ""

        query = f"""
        mutation CreatePost {{
          createPost(input: {{
            text: {json.dumps(text)}
            channelId: {json.dumps(channel["id"])}
            schedulingType: scheduled
            dueAt: {json.dumps(due_at_utc)}
            assets: [{{ video: {{ {video_asset} }} }}]
            {extra_input}
          }}) {{
            ... on PostActionSuccess {{
              post {{
                id
                text
                dueAt
                channelId
                assets {{
                  id
                  mimeType
                  source
                }}
              }}
            }}
            ... on MutationError {{
              message
            }}
          }}
        }}
        """
        data = self._graphql(query)
        result = data.get("createPost")
        if not result:
            raise BufferError("Buffer did not return a createPost result")
        if result.get("message"):
            raise BufferError(result["message"])
        post = result.get("post")
        if not post:
            raise BufferError("Buffer did not return the scheduled post")
        return {"post": post, "channel": channel}

    def create_scheduled_video_posts(
        self,
        text: str,
        due_at: str,
        video_url: str,
        thumbnail_url: str | None = None,
        text_by_service: dict[str, str] | None = None,
    ) -> list[dict]:
        return [
            self._create_scheduled_video_post_for_channel(
                channel=channel,
                text=(text_by_service or {}).get(canonical_buffer_service(channel.get("service")), text),
                due_at=due_at,
                video_url=video_url,
                thumbnail_url=thumbnail_url,
            )
            for channel in self.resolve_target_channels()
        ]


def package_public_url(public_base_url: str, package_id: str, filename: str) -> str:
    base = public_base_url.rstrip("/")
    return f"{base}/media/{quote(package_id)}/{quote(filename)}"


def build_post_text(package_dir: Path, service: str | None = None) -> str:
    metadata_path = package_dir / "metadata.json"
    if not metadata_path.exists():
        return "Tech news short"

    metadata = json.loads(metadata_path.read_text())
    platform_captions = metadata.get("platform_captions") or {}
    canonical_service = canonical_buffer_service(service)
    service_caption = ""
    if canonical_service:
        service_caption = (
            platform_captions.get(canonical_service)
            or platform_captions.get(str(service or ""))
            or ""
        )
    title = (metadata.get("title_options") or ["Tech news short"])[0]
    description = service_caption or metadata.get("description") or ""
    hashtags = " ".join(metadata.get("hashtags") or [])
    parts = [title, description, hashtags]
    text = "\n\n".join(part.strip() for part in parts if part and part.strip())

    lower_text = text.lower()
    cta_lines = []
    if "full ai briefing in bio" not in lower_text:
        cta_lines.append(CHANNEL_CTA_LINES[0])
    if "bit.ly/neural-drop" not in lower_text:
        cta_lines.append(CHANNEL_CTA_LINES[1])
    if cta_lines:
        text = f"{text}\n\n" + "\n".join(cta_lines)
    return text


def build_service_text_map(package_dir: Path) -> dict[str, str]:
    metadata_path = package_dir / "metadata.json"
    if not metadata_path.exists():
        return {}

    metadata = json.loads(metadata_path.read_text())
    platform_captions = metadata.get("platform_captions") or {}
    text_by_service: dict[str, str] = {}
    for raw_service in platform_captions:
        canonical_service = canonical_buffer_service(raw_service)
        if canonical_service:
            text_by_service[canonical_service] = build_post_text(package_dir, raw_service)
    return text_by_service
