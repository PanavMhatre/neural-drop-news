"""
Shared LLM call helper that works with OpenAI (beta.parse) and
NVIDIA NIM / Groq (json_object mode — they don't support json_schema structured outputs).
"""
import json
import logging
import re
from typing import Type, TypeVar

from openai import OpenAI
from pydantic import BaseModel

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_JSON_OBJECT_PROVIDERS = ("groq.com", "integrate.api.nvidia.com")


def _is_json_object_provider(client: OpenAI) -> bool:
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


def _repair_visual_plan(data: dict) -> dict:
    """If visual_plan items are strings instead of dicts, coerce them."""
    vp = data.get("visual_plan", [])
    if not vp or isinstance(vp[0], dict):
        return data
    repaired = []
    sections = ["hook", "move", "strategy", "industry_signal", "close"]
    for i, item in enumerate(vp):
        if isinstance(item, str):
            repaired.append({
                "section": sections[i] if i < len(sections) else f"section_{i}",
                "description": item,
                "text_overlay": None,
                "duration_hint": 8.0,
            })
        else:
            repaired.append(item)
    data["visual_plan"] = repaired
    return data


def llm_parse(
    client: OpenAI,
    model: str,
    messages: list[dict],
    response_model: Type[T],
    temperature: float = 0.7,
    max_tokens: int = 1500,
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
        completion = client.chat.completions.create(
            model=model,
            messages=msgs,
            response_format={"type": "json_object"},
            temperature=temperature,
            max_tokens=max_tokens,
        )
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
