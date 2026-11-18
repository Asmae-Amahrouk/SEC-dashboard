import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scraper"))

from classify import enrich, find_countries, find_cves  # noqa: E402
from feeds import normalize_url, parse_feed  # noqa: E402
from fetch_news import dedupe  # noqa: E402

FIX = ROOT / "tests" / "fixtures"


def test_parse_rss():
    items = parse_feed((FIX / "sample_rss.xml").read_bytes())
    assert len(items) == 2  # untitled item skipped
    first = items[0]
    assert first["url"] == "https://example.com/news/fortinet-zero-day?id=7"
    assert "actively exploited" in first["summary"] and "<b>" not in first["summary"]
    assert first["published"].isoformat() == "2026-11-17T14:05:00+00:00"


def test_parse_atom():
    (item,) = parse_feed((FIX / "sample_atom.xml").read_bytes())
    assert item["url"] == "https://example.org/2026/11/lockbit"
    assert item["published"].year == 2026


def test_normalize_url_rejects_non_http():
    assert normalize_url("javascript:alert(1)") == ""
    assert normalize_url("https://A.com/x?utm_medium=a#frag") == "https://a.com/x"


def test_enrich_zero_day():
    meta = enrich("Hackers exploit Fortinet zero-day CVE-2026-12345 in attacks on U.S. hospitals",
                  "Chinese state-sponsored hackers tracked as Volt Typhoon.", "cyber")
    assert meta["category"] == "cyber"
    assert meta["severity"] == "critical"
    assert {"zeroday", "vulnerability", "apt"} <= set(meta["topics"])
    assert meta["countries"][:2] == ["840", "156"]
    assert meta["cves"] == ["CVE-2026-12345"]
    assert meta["actors"] == ["Volt Typhoon"]


def test_enrich_ai_story_from_tech_source():
    meta = enrich("Anthropic launches Claude model with better agentic coding",
                  "The new LLM beats benchmarks.", "tech")
    assert meta["category"] == "ai"
    assert meta["severity"] == "info"


def test_cyber_story_from_ai_source_is_crossover():
    meta = enrich("Prompt injection flaw lets attackers steal data from AI agents", "", "ai")
    assert meta["crossover"] is True


def test_country_disambiguation():
    assert find_countries("Breach at Papua New Guinea tax office") == ["598"]
    assert find_countries("Latin American banks targeted") == []
    assert find_countries("North Korean IT workers") == ["408"]
    assert find_countries("A US firm and a UK bank") == ["840", "826"]
    assert find_countries("Indiana hospital hit") == []


def test_cve_dedup():
    assert find_cves("cve-2025-0001 and CVE-2025-0001, CVE-2024-99999") == ["CVE-2025-0001", "CVE-2024-99999"]


def test_dedupe_syndicated_titles():
    base = {"published": "2026-11-17T10:00:00Z", "category": "cyber"}
    arts = [
        {**base, "id": "a", "title": "Microsoft fixes 63 flaws in November Patch Tuesday", "source": "A"},
        {**base, "id": "b", "title": "Microsoft fixes 63 flaws in November Patch Tuesday!", "source": "B",
         "published": "2026-11-17T11:00:00Z"},
        {**base, "id": "c", "title": "Something else entirely", "source": "C"},
    ]
    out = dedupe(arts)
    assert [a["id"] for a in out] == ["a", "c"]
    assert out[0]["also_in"] == ["B"]


def test_severity_examples():
    assert enrich("Critical Cisco ISE flaw lets attackers run code as root", "", "cyber")["severity"] == "high"
    assert enrich("Chinese hackers breached US telecom firms", "", "cyber")["severity"] == "high"
    assert "incident" in enrich("Carmaker cyberattack halts production in UK plants", "", "cyber")["topics"]
    assert enrich("The best Black Friday laptop deals", "", "tech")["severity"] == "info"
