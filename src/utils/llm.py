"""
Shared LLM call helper that works with OpenAI (beta.parse) and
NVIDIA NIM / Groq (json_object mode — they don't support json_schema structured outputs).
"""
import json
import logging
from typing import Type, TypeVar

from openai import OpenAI
from pydantic import BaseModel

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# Providers that don't support beta.chat.completions.parse / json_schema response format
_JSON_OBJECT_PROVIDERS = ("groq.com", "integrate.api.nvidia.com")


def _is_json_object_provider(client: OpenAI) -> bool:
    base = str(getattr(client, "base_url", "")).lower()
    return any(p in base for p in _JSON_OBJECT_PROVIDERS)


def _schema_hint(model_cls: Type[T]) -> str:
    """Build a compact JSON schema hint to embed in the prompt."""
    schema = model_cls.model_json_schema()
    props = schema.get("properties", {})
    lines = []
    for k, v in props.items():
        t = v.get("type", v.get("anyOf", [{}])[0].get("type", "any"))
        lines.append(f'  "{k}": <{t}>')
    return "{\n" + ",\n".join(lines) + "\n}"


def llm_parse(
    client: OpenAI,
    model: str,
    messages: list[dict],
    response_model: Type[T],
    temperature: float = 0.7,
    max_tokens: int = 1200,
) -> T:
    """
    Call the LLM and parse the response into response_model.
    Uses beta.parse for OpenAI, json_object mode for NVIDIA/Groq.
    """
    if _is_json_object_provider(client):
        # Append schema hint to the last user message
        hint = f"\n\nRespond ONLY with a valid JSON object matching this schema:\n{_schema_hint(response_model)}"
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
