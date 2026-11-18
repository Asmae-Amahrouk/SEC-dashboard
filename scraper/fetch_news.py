#!/usr/bin/env python3
"""Fetch every configured feed, enrich the stories and write dashboard data.

Usage:
    python scraper/fetch_news.py                  # fetch + update docs/data
    python scraper/fetch_news.py --days 45        # keep a longer window
    python scraper/fetch_news.py --only bleepingcomputer,cisa

Outputs (consumed by docs/index.html):
    docs/data/news.json     rolling window of enriched articles + source health
    docs/data/history.json  per-day aggregate counts (kept for a year)
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
import urllib.error
import urllib.request
import zlib
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from classify import enrich  # noqa: E402
from countries import COUNTRIES  # noqa: E402
from feeds import parse_feed  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "sources.json"
DATA_DIR = ROOT / "docs" / "data"
USER_AGENT = "Mozilla/5.0 (compatible; SEC-dashboard/1.0; +https://github.com/)"
MAX_BYTES = 8 * 1024 * 1024
HISTORY_DAYS = 365


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def fetch(url: str, timeout: int = 25) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8",
            "Accept-Encoding": "gzip, deflate",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - URLs come from config
        data = resp.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError("feed larger than 8 MB")
        enc = resp.headers.get("Content-Encoding", "")
    if enc == "gzip":
        data = gzip.decompress(data)
    elif enc == "deflate":
        data = zlib.decompress(data)
    return data


def article_id(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()[:12]


def process_source(src: dict, now: datetime, cutoff: datetime) -> tuple[dict, list[dict]]:
    status = {"id": src["id"], "name": src["name"], "category": src["category"],
              "site": src.get("site", ""), "ok": False, "count": 0, "error": None}
    try:
        items = parse_feed(fetch(src["url"]))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        status["error"] = str(getattr(exc, "reason", exc))[:200]
        return status, []
    except Exception as exc:  # malformed XML etc. - never let one feed kill the run
        status["error"] = f"{type(exc).__name__}: {exc}"[:200]
        return status, []

    articles = []
    for it in items:
        published = it["published"] or now
        if published > now + timedelta(hours=2):
            published = now  # clamp feeds with bogus future dates
        if published < cutoff:
            continue
        meta = enrich(it["title"], it["summary"], src["category"])
        articles.append({
            "id": article_id(it["url"]),
            "title": it["title"],
            "url": it["url"],
            "summary": it["summary"],
            "source": src["name"],
            "source_id": src["id"],
            "published": published.isoformat(timespec="seconds").replace("+00:00", "Z"),
            **meta,
        })
    status.update(ok=True, count=len(articles))
    return status, articles


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _norm_title(t: str) -> str:
    return "".join(ch for ch in t.lower() if ch.isalnum() or ch == " ")


def dedupe(articles: list[dict]) -> list[dict]:
    """Drop same-URL duplicates and near-identical headlines (syndication)."""
    by_id: dict[str, dict] = {}
    for a in articles:
        by_id.setdefault(a["id"], a)
    result: list[dict] = []
    recent_titles: list[tuple[str, dict]] = []
    for a in sorted(by_id.values(), key=lambda x: x["published"]):
        nt = _norm_title(a["title"])
        window_start = (parse_iso(a["published"]) - timedelta(hours=72)).isoformat()
        recent_titles = [(t, k) for t, k in recent_titles if k["published"] >= window_start[:19]]
        dup = None
        for t, kept in recent_titles:
            sm = SequenceMatcher(None, t, nt)
            if sm.real_quick_ratio() > 0.92 and sm.quick_ratio() > 0.92 and sm.ratio() > 0.92:
                dup = kept
                break
        if dup is not None:
            also = dup.setdefault("also_in", [])
            if a["source"] != dup["source"] and a["source"] not in also:
                also.append(a["source"])
            continue
        recent_titles.append((nt, a))
        result.append(a)
    return result


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def build_history(articles: list[dict], previous: dict) -> dict:
    days: dict[str, dict] = {d["date"]: d for d in previous.get("days", [])}
    fresh: dict[str, dict] = defaultdict(lambda: {
        "total": 0, "category": Counter(), "severity": Counter(), "topics": Counter(), "countries": Counter()})
    for a in articles:
        day = fresh[a["published"][:10]]
        day["total"] += 1
        day["category"][a["category"]] += 1
        day["severity"][a["severity"]] += 1
        day["topics"].update(a["topics"])
        day["countries"].update(a["countries"])
    for date, d in fresh.items():  # days still inside the window are recomputed
        days[date] = {"date": date, "total": d["total"], "category": dict(d["category"]),
                      "severity": dict(d["severity"]), "topics": dict(d["topics"].most_common(15)),
                      "countries": dict(d["countries"].most_common(25))}
    oldest = (datetime.now(timezone.utc) - timedelta(days=HISTORY_DAYS)).date().isoformat()
    return {"days": sorted((d for k, d in days.items() if k >= oldest), key=lambda d: d["date"])}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=30, help="rolling window to keep (default 30)")
    ap.add_argument("--only", help="comma-separated source ids to fetch")
    ap.add_argument("--out", type=Path, default=DATA_DIR)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args(argv)

    sources = [s for s in json.loads(CONFIG.read_text(encoding="utf-8"))["sources"] if s.get("enabled", True)]
    if args.only:
        wanted = set(args.only.split(","))
        sources = [s for s in sources if s["id"] in wanted]

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=args.days)
    statuses, fetched = [], []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(process_source, s, now, cutoff): s for s in sources}
        for fut in as_completed(futures):
            status, arts = fut.result()
            statuses.append(status)
            fetched.extend(arts)
            log(f"  {'ok ' if status['ok'] else 'ERR'} {status['name']:<32} {status['count']:>4}"
                + (f"  ({status['error']})" if status["error"] else ""))

    args.out.mkdir(parents=True, exist_ok=True)
    news_path = args.out / "news.json"
    previous = load_json(news_path, {"articles": []})
    cutoff_iso = cutoff.isoformat(timespec="seconds").replace("+00:00", "Z")
    kept = [a for a in previous.get("articles", []) if a.get("published", "") >= cutoff_iso]
    # Fresh copies win so classification improvements apply to recent stories.
    merged = {a["id"]: a for a in kept}
    merged.update({a["id"]: a for a in fetched})
    articles = sorted(dedupe(list(merged.values())), key=lambda a: a["published"], reverse=True)

    ok = sum(s["ok"] for s in statuses)
    if ok == 0 and sources:
        log("No feed could be fetched - keeping existing data untouched.")
        return 1

    order = {s["id"]: i for i, s in enumerate(sources)}
    payload = {
        "generated_at": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "window_days": args.days,
        "sources": sorted(statuses, key=lambda s: order.get(s["id"], 999)),
        "country_names": {code: COUNTRIES[code][0] for code in sorted({c for a in articles for c in a["countries"]})
                          if code in COUNTRIES},
        "articles": articles,
    }
    news_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    history_path = args.out / "history.json"
    history = build_history(articles, load_json(history_path, {}))
    history_path.write_text(json.dumps(history, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log(f"Wrote {len(articles)} articles from {ok}/{len(sources)} sources -> {news_path.relative_to(ROOT)}"
        if news_path.is_relative_to(ROOT) else f"Wrote {len(articles)} articles -> {news_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
