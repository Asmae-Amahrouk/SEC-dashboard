import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scraper"))

import weekly_ideas  # noqa: E402
from classify import enrich  # noqa: E402

NOW = datetime(2026, 11, 16, 7, 0, tzinfo=timezone.utc)


def story(i, title, days_ago, category="cyber", source="Src"):
    meta = enrich(title, "", category)
    return {"id": f"s{i}", "title": title, "url": f"https://example.com/{i}", "summary": "", "source": f"{source}{i % 3}",
            "source_id": "x", "published": (NOW - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z"), **meta}


def sample_news():
    arts, i = [], 0
    week_titles = [
        ("Microsoft 365 outage knocks Outlook offline for 24 hours", "tech"),
        ("AWS outage disrupts services across Europe", "tech"),
        ("Cloudflare outage takes down thousands of sites", "tech"),
        ("Ransomware attack forces hospital to divert ambulances", "cyber"),
        ("Qilin ransomware gang hits manufacturer, production halted", "cyber"),
        ("Ransomware victims struggle to restore systems from backups", "cyber"),
        ("Critical Fortinet zero-day actively exploited in the wild", "cyber"),
        ("Chrome zero-day exploited in attacks, patch now", "cyber"),
        ("AI agents with broad access raise new identity risks", "ai"),
        ("New agentic AI framework lets agents run code autonomously", "ai"),
        ("Prompt injection flaw hijacks AI agents in coding tools", "ai"),
        ("<script>alert(1)</script> phishing campaign targets banks", "cyber"),
        ("Phishing kit bypasses MFA with fake login pages", "cyber"),
    ]
    for days in (1, 2, 3):
        for title, cat in week_titles:
            i += 1
            arts.append(story(i, f"{title} (day {days})", days, cat))
    for days in range(8, 28):  # quieter baseline with different themes
        for title in ("Microsoft fixes security flaws in monthly update", "Data breach exposes customer records",
                      "New malware strain spreads via fake apps"):
            i += 1
            arts.append(story(i, f"{title} {days}", days))
    return {"generated_at": NOW.isoformat().replace("+00:00", "Z"), "articles": arts}


def test_build_week_balanced_ideas():
    week = weekly_ideas.build_week(sample_news())
    assert week["week_id"] == "2026-W47"
    areas = [i["area"] for i in week["ideas"]]
    assert 3 <= len(areas) <= weekly_ideas.MAX_IDEAS
    assert {"drp", "cyber", "ai"} <= set(areas)
    for idea in week["ideas"]:
        assert idea["title"] and idea["why_now"] and idea["outline"] and idea["sources"]
        assert all(s["url"].startswith("https://") for s in idea["sources"])
    assert week["summary"]["history_ok"] is True


def test_email_escapes_headlines_and_has_clear_sections():
    week = weekly_ideas.build_week(sample_news())
    body = weekly_ideas.email_html(week, "https://example.github.io/SEC-dashboard/")
    assert "<script>alert(1)</script>" not in body
    for heading in ("This week in one minute", "Your blog ideas at a glance", "The ideas in detail", "Top stories of the week"):
        assert heading in body
    text = weekly_ideas.email_text(week, None)
    assert "IDEA 1 OF" in text and "Why now:" in text
    assert weekly_ideas.email_subject(week).startswith("SEC Pulse Weekly:")


def test_run_is_stable_within_a_week_and_skips_email_without_config(tmp_path, monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    (tmp_path / "news.json").write_text(json.dumps(sample_news()))
    week1, ok1 = weekly_ideas.run(tmp_path, email=True)
    week2, ok2 = weekly_ideas.run(tmp_path, email=True)
    assert ok1 and ok2
    assert week1["ideas"] == week2["ideas"]
    assert week2["emailed_at"] is None  # nothing configured, nothing sent
    store = json.loads((tmp_path / "ideas.json").read_text())
    assert len(store["weeks"]) == 1


def test_no_history_means_no_percentages():
    news = sample_news()
    news["articles"] = [a for a in news["articles"] if a["published"] >= "2026-11-09"]
    week = weekly_ideas.build_week(news)
    assert week["summary"]["history_ok"] is False
    assert all("%" not in i["why_now"] or "of all news" in i["why_now"] for i in week["ideas"])
