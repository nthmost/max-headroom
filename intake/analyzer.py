"""
AI-powered metadata classification using Claude.
"""

import json
import os
from config import CATEGORIES, classify_length

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

_CATEGORY_LIST = "\n".join(f"  - {c}" for c in CATEGORIES)

_PROMPT_TEMPLATE = """\
You are a media classifier for a retro-cyberpunk broadcast network.

Given the metadata below, choose the single best category from this list:
{categories}

Also determine the length bucket based on duration_seconds:
- short: under 5 minutes (< 300s)
- medium: 5-30 minutes (300-1799s)
- long: 30+ minutes (>= 1800s)
- unknown: if duration is missing or 0

Respond with ONLY a JSON object on one line:
{{"category": "<category>", "length": "<short|medium|long|unknown>", "reasoning": "<one sentence>"}}

Title: {title}
Duration: {duration}s
Channel/Creator: {channel}
Tags: {tags}
Description (first 300 chars): {description}
"""


def classify(metadata: dict) -> dict:
    """
    Given a metadata dict with title, description, tags, channel, duration_seconds,
    return {category, length, reasoning}.
    Falls back gracefully if ANTHROPIC_API_KEY is not set or the API call fails.
    """
    duration = metadata.get("duration_seconds") or 0

    if not ANTHROPIC_API_KEY:
        return {
            "category": CATEGORIES[0],
            "length": classify_length(duration),
            "reasoning": "No ANTHROPIC_API_KEY configured; defaults applied.",
        }

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        prompt = _PROMPT_TEMPLATE.format(
            categories=_CATEGORY_LIST,
            title=metadata.get("title", ""),
            duration=duration if duration else "unknown",
            channel=metadata.get("channel") or metadata.get("uploader") or "unknown",
            tags=", ".join((metadata.get("tags") or [])[:10]),
            description=(metadata.get("description") or "")[:300],
        )

        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )

        text = message.content[0].text.strip()
        result = json.loads(text)

        if result.get("category") not in CATEGORIES:
            result["category"] = CATEGORIES[0]
        if result.get("length") not in ("short", "medium", "long"):
            result["length"] = classify_length(duration)

        return result

    except Exception as exc:
        return {
            "category": CATEGORIES[0],
            "length": classify_length(duration),
            "reasoning": f"AI classification failed: {exc}",
        }
