"""Minimal, dependency-light RSS 2.0 / Atom / RDF parser."""
from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit, urlunsplit

try:  # Hardened XML parsing when available (protects against entity bombs).
    from defusedxml import ElementTree as ET  # type: ignore
except ImportError:  # pragma: no cover - stdlib fallback
    import xml.etree.ElementTree as ET  # noqa: N817

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_TRACKING_PARAMS = re.compile(r"^(utm_|fbclid|gclid|mc_|ref$|source$)")


def clean_text(raw: str | None, limit: int | None = None) -> str:
    if not raw:
        return ""
    text = html.unescape(_TAG_RE.sub(" ", raw))
    text = html.unescape(text)  # some feeds double-escape
    text = _WS_RE.sub(" ", text).strip()
    if limit and len(text) > limit:
        cut = text[:limit].rsplit(" ", 1)[0]
        text = cut.rstrip(",.;:") + "…"
    return text


def normalize_url(url: str) -> str:
    """Drop tracking query params and fragments so duplicates collapse."""
    url = (url or "").strip()
    try:
        parts = urlsplit(url)
    except ValueError:
        return ""
    if parts.scheme not in ("http", "https"):
        return ""
    query = "&".join(
        q for q in parts.query.split("&") if q and not _TRACKING_PARAMS.match(q.split("=", 1)[0])
    )
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path, query, ""))


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        dt = None
    if dt is None:
        iso = value.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(iso)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _child_text(el, *names: str) -> str | None:
    for child in el:
        if _local(child.tag) in names:
            text = "".join(child.itertext()) if len(child) else (child.text or "")
            if text.strip():
                return text
    return None


def _atom_link(el) -> str | None:
    fallback = None
    for child in el:
        if _local(child.tag) != "link":
            continue
        href = child.get("href")
        if not href:
            if child.text and child.text.strip():  # RSS <link>text</link>
                return child.text.strip()
            continue
        rel = child.get("rel", "alternate")
        if rel == "alternate":
            return href
        fallback = fallback or href
    return fallback


def parse_feed(payload: bytes) -> list[dict]:
    """Return a list of {title, url, summary, published} dicts."""
    root = ET.fromstring(payload)
    items = [el for el in root.iter() if _local(el.tag) in ("item", "entry")]
    out = []
    for el in items:
        title = clean_text(_child_text(el, "title"))
        url = normalize_url(_atom_link(el) or _child_text(el, "guid", "id") or "")
        if not title or not url:
            continue
        summary = clean_text(_child_text(el, "description", "summary", "encoded", "content"), limit=320)
        published = parse_date(_child_text(el, "pubdate", "published", "updated", "date", "issued"))
        out.append({"title": title, "url": url, "summary": summary, "published": published})
    return out
