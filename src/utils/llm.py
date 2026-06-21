"""
Shared LLM call helper that works with OpenAI (beta.parse) and
NVIDIA NIM / Groq (json_object mode — they don't support json_schema structured outputs).
"""
import json
import logging
import re
import time
from typing import Type, TypeVar

import httpx
from openai import OpenAI, RateLimitError, APITimeoutError, APIConnectionError
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class RotatingKeyClient:
    """Wraps multiple API keys for the same provider. On 429, rotates to the next key.

    Drop-in replacement for a bare OpenAI client anywhere llm_parse is called.
    Exposes .base_url and delegates attribute access so _is_json_object_provider works.
    """

    def __init__(self, keys: list[str], base_url: str, timeout: float = 20.0):
        self._keys = keys
        self._base_url = base_url
        self._timeout = timeout
        self._idx = 0
        self._clients = [
            OpenAI(api_key=k, base_url=base_url,
                   http_client=httpx.Client(timeout=timeout),
                   max_retries=0)  # we handle retries ourselves
            for k in keys
        ]

    @property
    def base_url(self):
        return self._base_url

    def _current(self) -> OpenAI:
        return self._clients[self._idx % len(self._clients)]

    def __getattr__(self, name):
        return getattr(self._current(), name)

    def call_with_rotation(self, fn_name: str, **kwargs):
        """Try each key in sequence on 429, with a short backoff between rotations."""
        start = self._idx
        for attempt in range(len(self._clients)):
            client = self._clients[(start + attempt) % len(self._clients)]
            try:
                fn = getattr(client, fn_name) if hasattr(client, fn_name) else None
                # Support nested attr like "chat.completions.create"
                obj = client
                for part in fn_name.split("."):
                    obj = getattr(obj, part)
                result = obj(**kwargs)
                self._idx = (start + attempt) % len(self._clients)
                return result
            except (RateLimitError, APITimeoutError, APIConnectionError) as exc:
                key_short = self._keys[(start + attempt) % len(self._keys)][:8]
                reason = "429 rate limit" if isinstance(exc, RateLimitError) else "timeout/connection"
                logger.warning(f"Key {key_short}... hit {reason} — rotating to next key")
                time.sleep(0.5)
        raise RuntimeError("All API keys exhausted (all returned 429, timeout, or connection error)")

T = TypeVar("T", bound=BaseModel)

_JSON_OBJECT_PROVIDERS = ("groq.com", "integrate.api.nvidia.com")


def _is_json_object_provider(client) -> bool:
    base = str(getattr(client, "base_url", "")).lower()
    return any(p in base for p in _JSON_OBJECT_PROVIDERS)


def _schema_hint(model_cls: Type[T]) -> str:
    """Build a detailed JSON schema hint, expanding nested models with examples."""
    schema = model_cls.model_json_schema()
    defs = schema.get("$defs", {})
    props = schema.get("properties", {})
    lines = []
    for k, v in props.items():
        # Resolve $ref
        ref = v.get("$ref") or (v.get("items", {}).get("$ref") if "items" in v else None)
        if ref:
            def_name = ref.split("/")[-1]
            nested = defs.get(def_name, {})
            nested_props = nested.get("properties", {})
            nested_ex = {nk: f"<{nv.get('type','str')}>" for nk, nv in nested_props.items()}
            if v.get("type") == "array" or "items" in v:
                lines.append(f'  "{k}": [{json.dumps(nested_ex)}]')
            else:
                lines.append(f'  "{k}": {json.dumps(nested_ex)}')
        elif v.get("type") == "array":
            item_type = v.get("items", {}).get("type", "str")
            lines.append(f'  "{k}": ["<{item_type}>"]')
        else:
            t = v.get("type", v.get("anyOf", [{}])[0].get("type", "str"))
            lines.append(f'  "{k}": <{t}>')
    return "{\n" + ",\n".join(lines) + "\n}"


def _parse_duration(val) -> float:
    """Convert duration_hint values like '3s', '0-3s', '3-12s', 8 → float seconds."""
    if isinstance(val, (int, float)):
        return float(val)
    if not isinstance(val, str):
        return 8.0
    val = val.strip().rstrip("s").strip()
    if "-" in val:
        parts = val.split("-")
        try:
            return (float(parts[0]) + float(parts[1])) / 2
        except ValueError:
            return 8.0
    try:
        return float(val)
    except ValueError:
        return 8.0


def _repair_visual_plan(data: dict) -> dict:
    """Coerce visual_plan items: string items → dicts, and fix duration_hint strings."""
    vp = data.get("visual_plan", [])
    if not vp:
        return data
    sections = ["hook", "move", "strategy", "industry_signal", "close"]
    repaired = []
    for i, item in enumerate(vp):
        if isinstance(item, str):
            repaired.append({
                "section": sections[i] if i < len(sections) else f"section_{i}",
                "description": item,
                "text_overlay": None,
                "duration_hint": 8.0,
            })
        elif isinstance(item, dict):
            item["duration_hint"] = _parse_duration(item.get("duration_hint", 8.0))
            repaired.append(item)
        else:
            repaired.append(item)
    data["visual_plan"] = repaired
    return data


def llm_parse(
    client,
    model: str,
    messages: list[dict],
    response_model: Type[T],
    temperature: float = 0.7,
    max_tokens: int = 2500,
) -> T:
    """
    Call the LLM and parse the response into response_model.
    Uses beta.parse for OpenAI, json_object mode for NVIDIA/Groq.
    """
    if _is_json_object_provider(client):
        hint = f"\n\nRespond ONLY with a valid JSON object matching this exact schema:\n{_schema_hint(response_model)}\nFor array fields containing objects, each item MUST be a JSON object with those exact keys, NOT a plain string."
        msgs = messages[:-1] + [
            {**messages[-1], "content": messages[-1]["content"] + hint}
        ]
        kwargs = dict(
            model=model,
            messages=msgs,
            response_format={"type": "json_object"},
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if isinstance(client, RotatingKeyClient):
            completion = client.call_with_rotation("chat.completions.create", **kwargs)
        else:
            completion = client.chat.completions.create(**kwargs)
        raw = completion.choices[0].message.content
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"LLM returned invalid JSON: {e}\nRaw: {raw[:500]}") from e
        # Repair known coercion issues before Pydantic validation
        data = _repair_visual_plan(data)
        return response_model(**data)
    else:
        completion = client.beta.chat.completions.parse(
            model=model,
            messages=messages,
            response_format=response_model,
            temperature=temperature,
        )
        result = completion.choices[0].message.parsed
        if result is None:
            raise ValueError(f"LLM refused: {completion.choices[0].message.refusal}")
        return result
