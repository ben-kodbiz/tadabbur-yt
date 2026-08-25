"""Upload pipeline metadata generation (§14).

Preserves original identity and provenance; never fabricates permission.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from pathlib import Path

from tadabbur.logging import stage_logger

logger = stage_logger("up-metadata")

MAX_YT_TITLE = 100
MAX_YT_DESCRIPTION = 5000


@dataclass
class UploadMetadata:
    title: str
    description: str
    tags: list[str]
    category_id: str
    privacy: str = "unlisted"

    def as_json(self) -> str:
        return json.dumps(
            {"title": self.title, "description": self.description,
             "tags": self.tags, "categoryId": self.category_id,
             "privacyStatus": self.privacy},
            ensure_ascii=False, indent=2,
        )


def build_title(original_title: str, speaker: str | None = None,
                *, template: str = "[Archive] {title} — {speaker}") -> str:
    """Archive title format: `[Archive] Original Title — Original Speaker`."""
    text = template.format(title=original_title.strip(), speaker=(speaker or "").strip())
    if len(text) > MAX_YT_TITLE:
        # Trim the title portion, keep the suffix intact where possible.
        suffix_len = len((speaker or "").strip()) + 12  # ' — ' + '[Archive] '
        keep = max(20, MAX_YT_TITLE - suffix_len)
        title_part = original_title.strip()[:keep].rstrip()
        if title_part != original_title.strip():
            title_part += "…"
        text = template.format(title=title_part, speaker=(speaker or "").strip())
        text = text[:MAX_YT_TITLE]
    return text


def build_description(
    *,
    original_title: str,
    source_name: str,
    source_url: str | None,
    original_url: str,
    rights_status: str,
    attribution_text: str | None = None,
    extra_permission_text: str | None = None,
) -> str:
    """Attribution-first description (§14 template). Never claims permission."""
    lines = [
        "ARCHIVE / ATTRIBUTION NOTICE",
        "",
        "This recording originates from the original source listed below.",
        "",
        f"Original title:\n{original_title}",
        "",
        f"Original speaker/channel:\n{source_name}",
        "",
    ]
    if source_url:
        lines += [f"Original source:\n{source_url}", ""]
    lines += [
        f"Original publication URL:\n{original_url}",
        "",
        "This channel acts as a central collection/archive and does not "
        "claim authorship of the original recording.",
        "",
        f"Rights status:\n{rights_status}",
        "",
    ]
    if extra_permission_text:
        lines += [extra_permission_text, ""]
    if attribution_text:
        lines += [attribution_text, ""]
    lines.append(
        "If you are the rights holder and believe this upload should be "
        "changed or removed, please contact the channel operator."
    )
    desc = "\n".join(lines)
    return desc[:MAX_YT_DESCRIPTION]


def build_metadata_record(
    *,
    original_title: str,
    speaker: str | None,
    source_name: str,
    source_url: str | None,
    original_url: str,
    rights_status: str,
    attribution_text: str | None = None,
    permission_note: str | None = None,
    tags: list[str] | None = None,
) -> UploadMetadata:
    """Full YouTube-ready metadata bundle."""
    title = build_title(original_title, speaker)
    description = build_description(
        original_title=original_title,
        source_name=speaker or source_name,
        source_url=source_url,
        original_url=original_url,
        rights_status=rights_status,
        attribution_text=attribution_text,
        extra_permission_text=(
            f"Permission reference: {permission_note}" if permission_note else None
        ),
    )
    safe_tags = [t for t in (tags or ["archive", "lecture", "islamic"]) if _safe_tag(t)]
    return UploadMetadata(title=title, description=description, tags=safe_tags[:15],
                          category_id="27")  # 27 = Education


def write_metadata_json(directory: Path, stem: str, meta: UploadMetadata) -> Path:
    path = directory / f"{stem}__metadata.json"
    path.write_text(meta.as_json(), encoding="utf-8")
    return path


def _safe_tag(tag: str) -> bool:
    return bool(re.fullmatch(r"[\w][\w \-']{0,30}", tag)) and not any(
        c in tag for c in "<>&"
    ) and tag == html.unescape(tag)
