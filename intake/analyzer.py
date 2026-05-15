"""
AI-powered metadata classification using Claude.
"""

import json
import logging
import os
import re

from config import CATEGORIES, classify_length

# Optional dep — module loads fine without it; classify() falls back to defaults.
try:
    import anthropic
except ImportError:  # pragma: no cover
    anthropic = None

log = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

_CATEGORY_LIST = "\n".join(f"  - {c}" for c in CATEGORIES)

_PROMPT_TEMPLATE = """\
You are a media classifier for a retro-cyberpunk broadcast network.

Pick the single best category from this list:
{categories}

Be decisive. Only use an existing category if it genuinely fits.
If nothing fits well, invent a concise snake_case category name.

Also suggest 2-5 descriptive tags for this media. Strongly prefer tags from this existing list:
{existing_tags}

Only invent a new tag if none of the existing ones fit. Tags must be snake_case.

Length bucket from duration:
- short < 300s, medium 300-1799s, long >= 1800s, unknown if missing

Respond with ONLY valid JSON, no prose:
{{"category": "<name>", "is_new_category": <true|false>, "length": "<short|medium|long|unknown>", "reasoning": "<10 words max>", "suggested_tags": ["tag1", "tag2"]}}

Title: {title}
Duration: {duration}s
Channel: {channel}
Tags: {tags}
Description: {description}
"""


def _sanitize_slug(s):
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def classify(metadata: dict, existing_tags: list = None) -> dict:
    """
    Given a metadata dict with title, description, tags, channel, duration_seconds,
    return {category, length, reasoning, suggested_tags}.
    Falls back gracefully if ANTHROPIC_API_KEY is not set or the API call fails.
    """
    duration = metadata.get("duration_seconds") or 0

    if not ANTHROPIC_API_KEY:
        return {
            "category": CATEGORIES[0],
            "length": classify_length(duration),
            "reasoning": "No ANTHROPIC_API_KEY configured; defaults applied.",
            "suggested_tags": [],
        }

    tag_list = existing_tags or []
    tag_sample = ", ".join(tag_list[:80])

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        prompt = _PROMPT_TEMPLATE.format(
            categories=_CATEGORY_LIST,
            existing_tags=tag_sample or "(none yet)",
            title=metadata.get("title", ""),
            duration=duration if duration else "unknown",
            channel=metadata.get("channel") or metadata.get("uploader") or "unknown",
            tags=", ".join((metadata.get("tags") or [])[:10]),
            description=(metadata.get("description") or "")[:300],
        )

        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=384,
            messages=[{"role": "user", "content": prompt}],
        )

        text = message.content[0].text.strip()
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if not m:
            raise ValueError(f"No JSON in response: {text[:200]!r}")
        result = json.loads(m.group(0))

        cat = result.get("category", "")
        is_new = result.get("is_new_category", False) or (cat not in CATEGORIES)
        if is_new and cat:
            cat = _sanitize_slug(cat)
        result["category"] = cat if cat else CATEGORIES[0]
        result["is_new_category"] = is_new and cat not in CATEGORIES
        if result.get("length") not in ("short", "medium", "long"):
            result["length"] = classify_length(duration)

        raw_tags = result.get("suggested_tags") or []
        result["suggested_tags"] = [_sanitize_slug(t) for t in raw_tags if t][:6]

        return result

    except Exception as exc:
        return {
            "category": CATEGORIES[0],
            "is_new_category": False,
            "length": classify_length(duration),
            "reasoning": f"AI classification failed: {exc}",
            "suggested_tags": [],
        }
