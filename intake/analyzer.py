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

Pick the single best category from this list:
{categories}

Be decisive. Only use an existing category if it genuinely fits.
If nothing fits well, invent a concise snake_case category name.

Length bucket from duration:
- short < 300s, medium 300-1799s, long >= 1800s, unknown if missing

Respond with ONLY valid JSON, no prose:
{{"category": "<name>", "is_new_category": <true|false>, "length": "<short|medium|long|unknown>", "reasoning": "<10 words max>"}}

Title: {title}
Duration: {duration}s
Channel: {channel}
Tags: {tags}
Description: {description}
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
        # Extract JSON object if the model wrapped it in prose
        m = __import__('re').search(r'\{.*\}', text, __import__('re').DOTALL)
        if not m:
            raise ValueError(f"No JSON in response: {text[:200]!r}")
        result = json.loads(m.group(0))

        cat = result.get("category", "")
        is_new = result.get("is_new_category", False) or (cat not in CATEGORIES)
        # Sanitise new category name to snake_case
        if is_new and cat:
            import re
            cat = re.sub(r"[^a-z0-9]+", "_", cat.lower()).strip("_")
        result["category"] = cat if cat else CATEGORIES[0]
        result["is_new_category"] = is_new and cat not in CATEGORIES
        if result.get("length") not in ("short", "medium", "long"):
            result["length"] = classify_length(duration)

        return result

    except Exception as exc:
        return {
            "category": CATEGORIES[0],
            "is_new_category": False,
            "length": classify_length(duration),
            "reasoning": f"AI classification failed: {exc}",
        }
