#!/usr/bin/env python3
"""Weekly blog-idea generator (rule-based, no API keys) + optional email.

It looks at the last 7 days of collected news, finds which themes are rising
compared with the 3 weeks before, and turns the strongest ones into blog
ideas for three areas: Cybersecurity, AI, and DRP / resilience. Each idea comes
with a title, the "why now" numbers, an angle, an outline and sources to read.

Usage:
    python scraper/weekly_ideas.py              # write docs/data/ideas.json
    python scraper/weekly_ideas.py --email      # ...and email it (once per week)
    python scraper/weekly_ideas.py --email --force   # regenerate and resend
    python scraper/weekly_ideas.py --preview out.html  # save the email as HTML

Email settings come from environment variables (GitHub secrets or Docker env):
    SMTP_HOST, SMTP_PORT (587 STARTTLS / 465 SSL), SMTP_USERNAME, SMTP_PASSWORD,
    EMAIL_TO (comma-separated), EMAIL_FROM (optional), DASHBOARD_URL (optional)
"""
from __future__ import annotations

import argparse
import html
import json
import os
import smtplib
import ssl
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from classify import TOPICS, find_topics  # noqa: E402
from countries import COUNTRIES  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "docs" / "data"
KEEP_WEEKS = 12
MAX_IDEAS = 6
MIN_BASELINE = 40  # stories needed in the 3 weeks before to compare trends

AREAS = {
    "cyber": "Cybersecurity",
    "ai": "AI",
    "drp": "DRP & resilience",
}

# ---------------------------------------------------------------------------
# Idea templates. Placeholders: {n} stories this week, {actor}, {country},
# {example} (headline of the top story). Titles are tried in order; the first
# whose placeholders can all be filled is used.
# ---------------------------------------------------------------------------
TEMPLATES: dict[str, dict] = {
    "ransomware": {
        "area": "drp",
        "titles": ["What this week's {actor} attacks teach us about ransomware recovery",
                   "{n} ransomware stories in 7 days: is your recovery faster than the attackers?"],
        "angle": "Skip the attack play-by-play. Focus on what decided how fast victims got back on their feet: "
                 "offline or immutable backups, tested restore times (RTO), and who decides between rebuilding and paying.",
        "outline": ["This week's incidents in one paragraph each", "Where recovery broke down: backups, identity, decisions",
                    "A 5-step ransomware recovery checklist", "How to test it: a 60-minute tabletop exercise"],
        "audience": "IT managers and DR / BCP owners",
    },
    "outage": {
        "area": "drp",
        "titles": ["Outages made {n} headlines this week: lessons in single points of failure",
                   "When it all goes down: what this week's outages teach about resilience"],
        "angle": "Use this week's outages as a case study: what failed, how long recovery took, how the provider "
                 "communicated, and what customers with a plan B did differently.",
        "outline": ["Timeline of the biggest outage", "Root cause vs. impact: why one fault spread so far",
                    "Questions to ask your own providers", "Designing for failure: redundancy, failover, manual workarounds"],
        "audience": "IT operations, DR planners, business leaders",
    },
    "backup": {
        "area": "drp",
        "titles": ["Backups are not a recovery plan: lessons from this week",
                   "{n} stories this week say the same thing: test your restores"],
        "angle": "Explain the gap between 'we have backups' and 'we can recover': immutability, isolation, restore "
                 "testing, and how insurers and regulators now ask for proof.",
        "outline": ["What this week's news reveals", "The 3-2-1-1-0 backup rule in plain words",
                    "How to run a restore test that means something", "Evidence to keep for auditors and insurers"],
        "audience": "IT teams and DR / BCP owners",
    },
    "recovery": {
        "area": "drp",
        "titles": ["How long would it take you to recover? A reality check from this week's incidents",
                   "Incident response lessons from this week: from first alert to back online"],
        "angle": "Compare what organisations in the news promised (RTO/RPO) with how long recovery really took, "
                 "and turn the difference into practical advice.",
        "outline": ["Recovery timelines from this week's news", "RTO and RPO explained with real examples",
                    "Why recovery is slower than planned (dependencies, identity, people)", "Three fixes you can start this month"],
        "audience": "DR planners, incident responders, management",
    },
    "continuity": {
        "area": "drp",
        "titles": ["Operational resilience in practice: what this week's news means for your BCP",
                   "Resilience is the new buzzword. Here's what it means in practice"],
        "angle": "Translate this week's resilience news (regulation such as DORA, frameworks, industry warnings) "
                 "into concrete changes to a business continuity plan.",
        "outline": ["What changed this week", "Resilience vs. continuity vs. disaster recovery: the difference",
                    "Updating your BCP: the 4 sections to revisit", "How to report resilience to management"],
        "audience": "BCP owners, risk and compliance teams",
    },
    "incident": {
        "area": "drp",
        "titles": ["From cyberattack to back in business: lessons from this week's incidents",
                   "{n} incident stories this week: what the recovery looked like"],
        "angle": "Look beyond the breach headline to the business impact: what stopped working, how long it took to "
                 "restore operations, and how the company communicated.",
        "outline": ["The incidents and their business impact", "What a good first 72 hours looks like",
                    "Communication: customers, staff, regulators", "Building a cyber-incident playbook into your DR plan"],
        "audience": "IT and business continuity teams",
    },
    "infrastructure": {
        "area": "drp",
        "titles": ["Hospitals, utilities, factories: why critical infrastructure keeps getting hit",
                   "Critical infrastructure under pressure: recovering when downtime is dangerous"],
        "angle": "Explain why OT and critical services are attractive targets and how recovery differs when "
                 "downtime affects safety, patients or production.",
        "outline": ["This week's critical-infrastructure incidents", "Why IT recovery playbooks don't fit OT",
                    "Manual fallback and degraded-mode operations", "What regulators now expect"],
        "audience": "OT, IT and continuity teams in critical sectors",
    },
    "supplychain": {
        "area": "drp",
        "titles": ["When your supplier gets hacked: supply-chain attacks and your continuity plan",
                   "{n} supply-chain stories this week: is a third party your weakest link?"],
        "angle": "Show how a compromise at a vendor, library or service provider becomes your outage, and how to "
                 "plan for it before it happens.",
        "outline": ["This week's supply-chain cases", "Mapping your critical suppliers and dependencies",
                    "Contract and SLA questions that matter", "Exit plans and alternative suppliers"],
        "audience": "Security, procurement and BCP teams",
    },
    "cloud": {
        "area": "drp",
        "titles": ["Cloud concentration risk: what happens when your provider has a bad week",
                   "Your cloud provider is a single point of failure. Plan for it"],
        "angle": "Use this week's cloud news to discuss shared-responsibility gaps, multi-region design and "
                 "what 'exit strategy' really means.",
        "outline": ["What happened this week", "Shared responsibility: what the provider will not recover for you",
                    "Multi-region vs. multi-cloud: costs and benefits", "A practical cloud resilience checklist"],
        "audience": "Cloud architects, IT managers",
    },
    "zeroday": {
        "area": "cyber",
        "titles": ["Zero-day week: what to do in the first 24 hours when there is no patch",
                   "Zero-days made {n} headlines this week: a first-24-hours playbook"],
        "angle": "Give readers a calm, step-by-step response for an exploited vulnerability: find exposure, "
                 "isolate, mitigate without a patch, monitor, and communicate.",
        "outline": ["This week's exploited flaws in one table", "Hour 0–4: exposure and isolation",
                    "Hour 4–24: mitigations, hunting, comms", "When to invoke your incident / DR plan"],
        "audience": "Security and IT operations teams",
    },
    "vulnerability": {
        "area": "cyber",
        "titles": ["{n} vulnerability stories in one week: how to decide what to patch first",
                   "Not every critical CVE is urgent: risk-based patching explained"],
        "angle": "Help readers decide what to patch first using exploitation status (CISA KEV), exposure and "
                 "business impact rather than CVSS alone.",
        "outline": ["This week's most important vulnerabilities", "Why CVSS alone misleads",
                    "A simple prioritisation matrix", "Emergency change process without breaking production"],
        "audience": "Security and IT teams",
    },
    "breach": {
        "area": "cyber",
        "titles": ["{n} breach stories in 7 days: the patterns behind the headlines",
                   "What this week's breaches have in common"],
        "angle": "Find the common root causes (stolen credentials, third parties, misconfiguration) and judge how "
                 "well each company detected, contained and disclosed the breach.",
        "outline": ["The breaches of the week", "Three root causes that keep repeating",
                    "Detection and disclosure: who did it well", "Five controls that would have helped"],
        "audience": "Security teams and business leaders",
    },
    "apt": {
        "area": "cyber",
        "titles": ["{actor} in the news: what nation-state hacking means for ordinary companies",
                   "Nation-state hacking this week: why it matters even if you're not a target"],
        "angle": "Explain the campaigns without hype: who is behind them, what they want, and why mid-size "
                 "companies end up as stepping stones.",
        "outline": ["The campaigns of the week", "Who the actors are and what they want",
                    "How companies become collateral damage", "Defensive basics that blunt advanced attacks"],
        "audience": "Security-curious professionals",
    },
    "malware": {
        "area": "cyber",
        "titles": ["The malware of the week, explained without jargon",
                   "Infostealers and loaders: what this week's malware tells us"],
        "angle": "Explain how this week's malware gets in, what it steals, and how to spot it, in plain language.",
        "outline": ["The malware families in the news", "How the infection works step by step",
                    "Signs to look for", "Protection that actually helps"],
        "audience": "General IT audience",
    },
    "phishing": {
        "area": "cyber",
        "titles": ["This week's phishing tricks and how to train people for them",
                   "{n} phishing stories this week: the lures are getting smarter"],
        "angle": "Show real examples of new lures and turn them into short awareness lessons.",
        "outline": ["The new lures of the week", "Why they work (psychology)", "Technical defences",
                    "A 10-minute awareness session you can reuse"],
        "audience": "Everyone. Good for a broad audience",
    },
    "identity": {
        "area": "cyber",
        "titles": ["Identity is the new perimeter: {n} stories on credentials and account takeover",
                   "Passwords, MFA and stolen sessions: the identity lessons of the week"],
        "angle": "Connect the week's credential and MFA stories to a simple identity-security roadmap.",
        "outline": ["What happened this week", "How attackers bypass MFA", "Phishing-resistant MFA and passkeys",
                    "Recovering identity systems after a compromise"],
        "audience": "IT and security teams",
    },
    "fraud": {
        "area": "cyber",
        "titles": ["Scams and crypto theft this week: how the money disappears",
                   "{n} fraud stories this week: the scams to warn people about"],
        "angle": "Walk through the scams, how victims were targeted, and practical advice for readers and companies.",
        "outline": ["The scams of the week", "How they worked", "Warning signs", "What to do if you're hit"],
        "audience": "Broad audience",
    },
    "lawenforcement": {
        "area": "cyber",
        "titles": ["Arrests and takedowns this week: do they really reduce cybercrime?",
                   "Inside this week's cybercrime takedowns"],
        "angle": "Look at the operations critically: what was disrupted, how long the effect lasts, and what "
                 "defenders should do while criminals regroup.",
        "outline": ["The operations of the week", "What gets disrupted and what doesn't",
                    "How criminal groups rebuild", "What it means for defenders"],
        "audience": "Security professionals",
    },
    "privacy": {
        "area": "cyber",
        "titles": ["Fines, rules and lawsuits: this week's privacy news and your security program",
                   "Regulators are watching: the privacy and compliance lessons of the week"],
        "angle": "Translate the week's regulatory and legal news into concrete actions for security teams.",
        "outline": ["The rulings and fines", "What regulators criticised", "Controls to check", "How to brief management"],
        "audience": "Security, privacy and compliance teams",
    },
    "aisecurity": {
        "area": "ai",
        "titles": ["Attacking the AI: prompt injection, jailbreaks and deepfakes this week",
                   "{n} AI security stories this week: the risks your AI tools bring"],
        "angle": "Explain the new attacks against AI systems and the practical controls organisations should add "
                 "before rolling AI out widely.",
        "outline": ["This week's AI security incidents and research", "Prompt injection explained simply",
                    "Deepfakes and AI-powered social engineering", "An AI security checklist for teams"],
        "audience": "Security and AI practitioners",
    },
    "agents": {
        "area": "ai",
        "titles": ["AI agents are getting access to everything. Who is watching them?",
                   "{n} stories on AI agents this week: autonomy, access and risk"],
        "angle": "Discuss what happens when AI agents act on systems with real permissions: identity, logging, "
                 "guardrails, and how to roll back when an agent makes a mistake.",
        "outline": ["What's new with AI agents this week", "The access problem: agents as non-human identities",
                    "Guardrails, approvals and audit logs", "Planning for agent failures and rollback"],
        "audience": "IT, security and AI teams",
    },
    "llm": {
        "area": "ai",
        "titles": ["The week in LLMs: what's actually useful for security and IT teams",
                   "New AI models this week, translated for practitioners"],
        "angle": "Filter the week's AI announcements down to what matters for security, IT and resilience work.",
        "outline": ["The announcements of the week", "What's genuinely new vs. marketing",
                    "Practical uses in security / IT / DR", "Risks and how to pilot safely"],
        "audience": "Tech professionals",
    },
    "aipolicy": {
        "area": "ai",
        "titles": ["AI rules are coming: what this week's policy news means for your organisation",
                   "AI regulation this week, explained in plain words"],
        "angle": "Summarise the policy moves and give a short, practical compliance to-do list.",
        "outline": ["The policy news", "Who it applies to", "What to document now", "How it connects to security and risk"],
        "audience": "Managers, risk and compliance",
    },
    "airesearch": {
        "area": "ai",
        "titles": ["This week's AI research, explained for practitioners",
                   "Benchmarks, models and papers: the AI research that matters this week"],
        "angle": "Pick the 2–3 research results with real-world impact and explain them simply.",
        "outline": ["The research highlights", "Why they matter", "Limits and caveats", "What to try or watch next"],
        "audience": "AI-curious professionals",
    },
    "compute": {
        "area": "ai",
        "titles": ["AI's chip and power crunch: a resilience risk nobody planned for",
                   "Data centres, GPUs and power: the infrastructure side of AI this week"],
        "angle": "Connect AI infrastructure news (chips, data centres, power, export rules) to availability and "
                 "continuity risks for organisations that depend on AI services.",
        "outline": ["The infrastructure news of the week", "Concentration and supply risks",
                    "What happens to your AI-dependent processes in an outage", "Building fallback options"],
        "audience": "IT leaders and architects",
    },
    "aibusiness": {
        "area": "ai",
        "titles": ["Following the money: what this week's AI deals say about security",
                   "AI acquisitions and funding this week: what they signal"],
        "angle": "Read the deals as signals: where investors and vendors think security and AI are heading.",
        "outline": ["The deals of the week", "Patterns and trends", "What it means for buyers", "Predictions"],
        "audience": "Tech and business readers",
    },
}

# Crossover ideas when two themes show up together in the same stories.
COMBOS = [
    {"needs": ({"agents", "llm", "aisecurity"}, {"identity"}), "area": "ai",
     "title": "AI agents inherit your employees' access: a practical guardrail checklist",
     "angle": "Bridge AI and security: treat agents as identities, with least privilege, approvals and audit trails.",
     "outline": ["Why agents are an identity problem", "This week's examples", "Least privilege for agents",
                 "Monitoring and kill switches"], "audience": "Security and AI teams"},
    {"needs": ({"outage"}, {"cloud", "bigtech"}), "area": "drp",
     "title": "When a tech giant goes dark: planning for your provider's outage",
     "angle": "Use this week's big-provider outage to show how to design and document a plan B for SaaS and cloud.",
     "outline": ["What failed and for how long", "Which business processes stopped", "Plan B options for SaaS",
                 "Communication templates for staff"], "audience": "IT managers and DR planners"},
    {"needs": ({"ransomware"}, {"infrastructure"}), "area": "drp",
     "title": "Ransomware in hospitals and plants: recovering when downtime is dangerous",
     "angle": "Focus on degraded operations and safe recovery when systems that keep people safe are down.",
     "outline": ["This week's cases", "Manual fallback procedures", "Recovery priorities", "Testing it safely"],
     "audience": "Continuity teams in critical sectors"},
    {"needs": ({"llm", "agents", "aisecurity"}, {"recovery", "continuity", "incident", "backup"}), "area": "ai",
     "title": "AI in incident response and disaster recovery: hype vs. real help",
     "angle": "Where AI genuinely speeds up detection, triage and recovery, and where it adds new failure points.",
     "outline": ["What vendors promise", "Where AI helps today", "New risks AI adds to your DR plan",
                 "A sensible pilot"], "audience": "Security and DR teams"},
    {"needs": ({"zeroday", "vulnerability"}, {"incident", "outage"}), "area": "drp",
     "title": "From unpatched flaw to full outage: connecting vulnerability management and DR",
     "angle": "Show how an exploited vulnerability turns into a business outage, and where DR planning should meet patching.",
     "outline": ["This week's chain of events", "Where the hand-offs failed", "Joint playbooks for security and IT ops",
                 "Metrics both teams should share"], "audience": "Security and IT operations"},
]


# ---------------------------------------------------------------------------
def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def story_rank(a: dict) -> tuple:
    return (a.get("score", 0), len(a.get("also_in", [])), a["published"])


def lower_first(text: str) -> str:
    """'Outages & downtime' -> 'outages & downtime', but keep 'AI agents'."""
    return text[0].lower() + text[1:] if len(text) > 1 and text[1].islower() else text


def short(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "…"


def trend_info(now_n: int, now_total: int, prev_n: int, prev_total: int) -> dict:
    """Compare a theme's share of all stories this week with its share before.

    Shares (not raw counts) keep the comparison fair when the amount of
    collected news differs between periods. Without enough history there is
    no comparison."""
    now_share = now_n / now_total if now_total else 0.0
    info = {"this_week": now_n, "share_pct": round(now_share * 100, 1), "share_before_pct": None,
            "change_pct": None, "label": "No history yet"}
    if prev_total < MIN_BASELINE:
        return info
    prev_share = prev_n / prev_total
    info["share_before_pct"] = round(prev_share * 100, 1)
    if prev_n == 0:
        info["label"] = "New this week" if now_n else "Quiet"
        return info
    change = round((now_share - prev_share) / prev_share * 100)
    info["change_pct"] = change
    info["label"] = "Rising fast" if change >= 75 else "Rising" if change >= 20 else "Falling" if change <= -20 else "Steady"
    return info


def fill(template: str, ctx: dict) -> str | None:
    try:
        out = template.format(**ctx)
    except KeyError:
        return None
    return out


def build_week(news: dict) -> dict:
    articles = news.get("articles", [])
    anchor = parse_iso(news["generated_at"]) if news.get("generated_at") else datetime.now(timezone.utc)
    start = anchor - timedelta(days=7)
    base_start = anchor - timedelta(days=28)

    week = [a for a in articles if parse_iso(a["published"]) >= start]
    before = [a for a in articles if base_start <= parse_iso(a["published"]) < start]

    now_topics = Counter(t for a in week for t in a.get("topics", []))
    prev_topics = Counter(t for a in before for t in a.get("topics", []))

    def trend(t: str) -> dict:
        return trend_info(now_topics[t], len(week), prev_topics[t], len(before))

    def momentum(t: str) -> float:
        info = trend(t)
        if info["share_before_pct"] is None:
            return 1.0
        return min(3.0, (info["share_pct"] + 1) / (info["share_before_pct"] + 1))

    def relevant(stories: list[dict], topic_ids: set[str]) -> list[dict]:
        """Stories whose headline itself is about the theme come first."""
        return sorted(stories, key=lambda a: (bool(topic_ids & set(find_topics(a["title"]))),) + story_rank(a),
                      reverse=True)

    def context(stories: list[dict]) -> dict:
        ctx: dict = {"n": len(stories)}
        actors = Counter(x for a in stories for x in a.get("actors", []))
        if actors and actors.most_common(1)[0][1] >= 2:
            ctx["actor"] = actors.most_common(1)[0][0]
        countries = Counter(c for a in stories for c in a.get("countries", []))
        if countries:
            code = countries.most_common(1)[0][0]
            ctx["country"] = COUNTRIES.get(code, (code,))[0]
        ctx["example"] = short(stories[0]["title"], 70)
        return ctx

    def sources_for(stories: list[dict]) -> list[dict]:
        out, seen_src = [], Counter()
        for a in stories:  # already sorted by relevance
            if seen_src[a["source"]] >= 2:
                continue
            seen_src[a["source"]] += 1
            out.append({"title": a["title"], "url": a["url"], "source": a["source"], "published": a["published"]})
            if len(out) == 4:
                break
        return out

    candidates = []
    for tid, tpl in TEMPLATES.items():
        n = now_topics[tid]
        if n < 2:
            continue
        stories = relevant([a for a in week if tid in a.get("topics", [])], {tid})
        severity = sum(a.get("score", 0) for a in stories) / max(1, len(stories))
        ctx = context(stories)
        title = next((t for t in (fill(x, ctx) for x in tpl["titles"]) if t), tpl["titles"][-1])
        candidates.append({
            "key": tid, "area": tpl["area"], "title": title,
            "score": n * momentum(tid) + severity, "trend": trend(tid),
            "theme": TOPICS[tid][1], "angle": tpl["angle"], "outline": tpl["outline"], "audience": tpl["audience"],
            "sources": sources_for(stories), "stories": stories,
        })

    for combo in COMBOS:
        a_set, b_set = combo["needs"]
        stories = relevant([a for a in week if a_set & set(a.get("topics", [])) and b_set & set(a.get("topics", []))],
                           a_set | b_set)
        if len(stories) < 2:
            continue
        candidates.append({
            "key": "combo:" + "+".join(sorted(a_set | b_set)), "area": combo["area"], "title": combo["title"],
            "score": len(stories) * 2.5 + 2,
            "trend": {"this_week": len(stories), "share_pct": None, "share_before_pct": None, "change_pct": None,
                      "label": "Crossover"},
            "theme": " + ".join(sorted({TOPICS[t][1] for t in a_set | b_set if t in TOPICS}))[:80],
            "angle": combo["angle"], "outline": combo["outline"], "audience": combo["audience"],
            "sources": sources_for(stories), "stories": stories,
        })

    # Pick a balanced set: up to 2 per area first, then the best of the rest.
    candidates.sort(key=lambda c: c["score"], reverse=True)
    chosen, used_urls = [], set()

    def overlaps(c: dict) -> bool:
        urls = {s["url"] for s in c["sources"]}
        return len(urls & used_urls) >= max(2, len(urls) - 1)

    for area in ("drp", "cyber", "ai"):
        for c in [c for c in candidates if c["area"] == area and c not in chosen][:4]:
            if sum(x["area"] == area for x in chosen) >= 2 or overlaps(c):
                continue
            chosen.append(c)
            used_urls |= {s["url"] for s in c["sources"]}
    for c in candidates:
        if len(chosen) >= MAX_IDEAS:
            break
        if c not in chosen and not overlaps(c):
            chosen.append(c)
            used_urls |= {s["url"] for s in c["sources"]}
    chosen.sort(key=lambda c: (("drp", "cyber", "ai").index(c["area"]), -c["score"]))

    ideas = []
    for i, c in enumerate(chosen[:MAX_IDEAS], 1):
        t = c["trend"]
        if t["label"] == "Crossover":
            why = f"{t['this_week']} stories this week combine these themes."
        elif t["label"] == "No history yet":
            why = f"{t['this_week']} stories this week on {lower_first(c['theme'])} ({t['share_pct']:g}% of all news)."
        elif t["change_pct"] is None:
            why = f"{t['this_week']} stories this week on {lower_first(c['theme'])}, a theme that was quiet the 3 weeks before."
        else:
            why = (f"{t['this_week']} stories this week on {lower_first(c['theme'])}: {t['share_pct']:g}% of all news, "
                   f"compared with {t['share_before_pct']:g}% over the 3 weeks before ({t['label'].lower()}).")
        top = c["stories"][0]
        why += f" Biggest story: \"{short(top['title'], 90)}\" ({top['source']})."
        ideas.append({
            "number": i, "area": c["area"], "area_label": AREAS[c["area"]], "title": c["title"],
            "theme": c["theme"], "trend": t, "why_now": why, "angle": c["angle"], "outline": c["outline"],
            "audience": c["audience"], "sources": c["sources"],
        })

    # Week summary
    cats = Counter(a["category"] for a in week)
    rising = sorted((tid for tid in now_topics if now_topics[tid] >= 3 and tid in TOPICS),
                    key=lambda t: (momentum(t), now_topics[t]), reverse=True)[:3]
    top_stories = [{"title": a["title"], "url": a["url"], "source": a["source"], "severity": a.get("severity", "info")}
                   for a in sorted(week, key=story_rank, reverse=True)[:5]]
    iso = anchor.isocalendar()
    return {
        "week_id": f"{iso.year}-W{iso.week:02d}",
        "label": f"{start:%d %b} – {anchor:%d %b %Y}",
        "period": {"from": start.isoformat(timespec="seconds"), "to": anchor.isoformat(timespec="seconds")},
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "summary": {
            "stories": len(week),
            "by_area": {"cyber": cats["cyber"], "ai": cats["ai"], "tech": cats["tech"],
                        "drp": sum(1 for a in week if a.get("drp"))},
            "critical_high": sum(1 for a in week if a.get("severity") in ("critical", "high")),
            "rising": [{"theme": TOPICS[t][1], "this_week": now_topics[t], "trend": trend(t)["label"]} for t in rising],
            "history_ok": len(before) >= MIN_BASELINE,
            "top_stories": top_stories,
        },
        "ideas": ideas,
        "emailed_at": None,
    }


# ---------------------------------------------------------------------------
# Email rendering
# ---------------------------------------------------------------------------
AREA_COLORS = {"cyber": "#2a78d6", "ai": "#d95926", "drp": "#6250d6"}
E = html.escape


def email_subject(week: dict) -> str:
    return f"SEC Pulse Weekly: {len(week['ideas'])} blog ideas for {week['label']} (Cyber · AI · DRP)"


def email_text(week: dict, dashboard_url: str | None) -> str:
    s = week["summary"]
    lines = [f"SEC PULSE WEEKLY  |  {week['label']}", "Blog ideas for Cybersecurity, AI and DRP", "=" * 60, "",
             "1. THIS WEEK IN ONE MINUTE", "-" * 60,
             f"- {s['stories']} stories: {s['by_area']['cyber']} cyber, {s['by_area']['ai']} AI, "
             f"{s['by_area']['tech']} IT/tech ({s['by_area']['drp']} about resilience/DRP)",
             f"- {s['critical_high']} critical or high severity security stories"]
    for r in s["rising"]:
        lines.append(f"- Rising theme: {r['theme']} ({r['this_week']} stories, {r['trend'].lower()})")
    lines += ["", f"2. YOUR BLOG IDEAS ({len(week['ideas'])})", "-" * 60]
    for idea in week["ideas"]:
        lines += ["", f"IDEA {idea['number']} OF {len(week['ideas'])}  [{idea['area_label'].upper()}]",
                  f"Title: {idea['title']}", "", f"Why now: {idea['why_now']}", f"Angle: {idea['angle']}",
                  f"Audience: {idea['audience']}", "Outline:"]
        lines += [f"  {i}. {step}" for i, step in enumerate(idea["outline"], 1)]
        lines.append("Read first:")
        lines += [f"  - {src['title']} ({src['source']})\n    {src['url']}" for src in idea["sources"]]
    lines += ["", "3. TOP STORIES OF THE WEEK", "-" * 60]
    lines += [f"- {a['title']} ({a['source']})\n  {a['url']}" for a in s["top_stories"]]
    if dashboard_url:
        lines += ["", f"Open the dashboard: {dashboard_url}", f"All blog ideas: {dashboard_url.rstrip('/')}/ideas.html"]
    lines += ["", "You get this email from your SEC Pulse project (weekly ideas workflow)."]
    return "\n".join(lines)


def email_html(week: dict, dashboard_url: str | None) -> str:
    s = week["summary"]
    font = "font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;"
    h2 = f"{font}font-size:13px;letter-spacing:.08em;text-transform:uppercase;color:#52514e;margin:28px 0 10px;"

    def link(url: str, text: str) -> str:
        safe = url if url.startswith(("http://", "https://")) else "#"
        return f'<a href="{E(safe)}" style="color:#1c5cab;text-decoration:none;">{E(text)}</a>'

    rising = "".join(f"<li>Rising theme: <b>{E(r['theme'])}</b> ({r['this_week']} stories, {E(r['trend'].lower())})</li>"
                     for r in s["rising"])
    toc = "".join(
        f'<tr><td style="{font}font-size:14px;padding:4px 0;color:#0b0b0b;">'
        f'<span style="display:inline-block;min-width:22px;font-weight:700;">{i["number"]}.</span>'
        f'<span style="color:{AREA_COLORS[i["area"]]};font-weight:700;font-size:11px;text-transform:uppercase;letter-spacing:.05em;">'
        f'{E(i["area_label"])}</span> · {E(i["title"])}</td></tr>' for i in week["ideas"])

    cards = []
    for idea in week["ideas"]:
        color = AREA_COLORS[idea["area"]]
        outline = "".join(f"<li style='margin:2px 0;'>{E(step)}</li>" for step in idea["outline"])
        srcs = "".join(f"<li style='margin:4px 0;'>{link(x['url'], x['title'])} <span style='color:#898781;'>· {E(x['source'])}</span></li>"
                       for x in idea["sources"])
        cards.append(f"""
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e1e0d9;border-left:4px solid {color};border-radius:10px;margin:0 0 16px;background:#ffffff;">
<tr><td style="padding:16px 18px;{font}color:#0b0b0b;">
  <div style="font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:{color};">Idea {idea['number']} of {len(week['ideas'])} · {E(idea['area_label'])}</div>
  <div style="font-size:19px;line-height:1.3;font-weight:700;margin:6px 0 12px;">{E(idea['title'])}</div>
  <div style="font-size:14px;line-height:1.5;margin:0 0 8px;"><b>Why now:</b> {E(idea['why_now'])}</div>
  <div style="font-size:14px;line-height:1.5;margin:0 0 8px;"><b>Your angle:</b> {E(idea['angle'])}</div>
  <div style="font-size:14px;line-height:1.5;margin:0 0 4px;"><b>Suggested outline:</b></div>
  <ol style="font-size:14px;line-height:1.45;margin:0 0 8px;padding-left:22px;">{outline}</ol>
  <div style="font-size:14px;line-height:1.5;margin:0 0 4px;"><b>Read first:</b></div>
  <ul style="font-size:13.5px;line-height:1.4;margin:0 0 8px;padding-left:20px;">{srcs}</ul>
  <div style="font-size:13px;color:#52514e;"><b>Best for:</b> {E(idea['audience'])}</div>
</td></tr></table>""")

    top = "".join(f"<li style='margin:5px 0;'>{link(a['url'], a['title'])} <span style='color:#898781;'>· {E(a['source'])}</span></li>"
                  for a in s["top_stories"])
    footer_links = ""
    if dashboard_url:
        base = dashboard_url.rstrip("/")
        footer_links = (f'<p style="{font}font-size:14px;margin:24px 0 0;">{link(base + "/", "Open the dashboard →")}'
                        f' &nbsp;·&nbsp; {link(base + "/ideas.html", "All blog ideas →")}</p>')
    return f"""<!doctype html><html><body style="margin:0;padding:0;background:#f4f4f1;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f1;"><tr><td align="center" style="padding:24px 12px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:640px;">
<tr><td style="{font}color:#0b0b0b;">
  <div style="font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:#2a78d6;">SEC Pulse Weekly</div>
  <h1 style="font-size:26px;line-height:1.2;margin:4px 0 4px;">Your blog ideas for {E(week['label'])}</h1>
  <div style="font-size:14px;color:#52514e;">Cybersecurity · AI · DRP &amp; resilience: {len(week['ideas'])} ideas based on this week's news</div>

  <div style="{h2}">1 · This week in one minute</div>
  <ul style="font-size:14px;line-height:1.6;margin:0;padding-left:20px;">
    <li><b>{s['stories']}</b> stories: {s['by_area']['cyber']} cyber, {s['by_area']['ai']} AI, {s['by_area']['tech']} IT/tech ({s['by_area']['drp']} about resilience/DRP)</li>
    <li><b>{s['critical_high']}</b> critical or high severity security stories</li>
    {rising}
  </ul>

  <div style="{h2}">2 · Your blog ideas at a glance</div>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0">{toc}</table>

  <div style="{h2}">3 · The ideas in detail</div>
  {''.join(cards)}

  <div style="{h2}">4 · Top stories of the week</div>
  <ul style="font-size:14px;line-height:1.45;margin:0;padding-left:20px;">{top}</ul>
  {footer_links}
  <p style="font-size:12px;color:#898781;margin:28px 0 0;">Ideas are generated by keyword rules from public headlines. Check the sources before you write.
  You get this email from your own SEC Pulse project. To stop it, disable the "Weekly blog ideas" workflow.</p>
</td></tr></table></td></tr></table></body></html>"""


def send_email(week: dict) -> bool:
    host = os.environ.get("SMTP_HOST", "").strip()
    to = [x.strip() for x in os.environ.get("EMAIL_TO", "").split(",") if x.strip()]
    if not host or not to:
        print("Email not configured (set SMTP_HOST and EMAIL_TO). Skipping email.", file=sys.stderr)
        return False
    port = int(os.environ.get("SMTP_PORT") or 587)
    user = os.environ.get("SMTP_USERNAME", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "")
    sender = os.environ.get("EMAIL_FROM", "").strip() or user or to[0]
    dashboard = os.environ.get("DASHBOARD_URL", "").strip() or None

    msg = EmailMessage()
    msg["Subject"] = email_subject(week)
    msg["From"] = formataddr(("SEC Pulse", sender))
    msg["To"] = ", ".join(to)
    msg["Message-ID"] = make_msgid(domain="sec-pulse.local")
    msg.set_content(email_text(week, dashboard))
    msg.add_alternative(email_html(week, dashboard), subtype="html")

    ctx = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ctx, timeout=30) as smtp:
            if user:
                smtp.login(user, password)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.starttls(context=ctx)
            if user:
                smtp.login(user, password)
            smtp.send_message(msg)
    print(f"Weekly email sent to {len(to)} recipient(s).", file=sys.stderr)
    return True


# ---------------------------------------------------------------------------
def run(data_dir: Path = DATA_DIR, email: bool = False, force: bool = False,
        preview: Path | None = None) -> tuple[dict | None, bool]:
    """Generate (or reuse) this week's ideas. Returns (week, email_ok)."""
    news_path = data_dir / "news.json"
    ideas_path = data_dir / "ideas.json"
    try:
        news = json.loads(news_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        print("No news.json yet. Run fetch_news.py first.", file=sys.stderr)
        return None, True
    if not news.get("articles"):
        print("news.json has no articles yet.", file=sys.stderr)
        return None, True
    try:
        store = json.loads(ideas_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        store = {"weeks": []}

    week = build_week(news)
    existing = next((w for w in store["weeks"] if w["week_id"] == week["week_id"]), None)
    if existing and not force:
        week = existing  # keep this week's ideas stable once generated
    else:
        if existing:
            week["emailed_at"] = existing.get("emailed_at")
        store["weeks"] = [w for w in store["weeks"] if w["week_id"] != week["week_id"]] + [week]
        store["weeks"] = sorted(store["weeks"], key=lambda w: w["week_id"], reverse=True)[:KEEP_WEEKS]

    if preview:
        preview.write_text(email_html(week, os.environ.get("DASHBOARD_URL") or None), encoding="utf-8")
        print(f"Email preview written to {preview}", file=sys.stderr)
    email_ok = True
    if email and (force or not week.get("emailed_at")):
        try:
            if send_email(week):
                week["emailed_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        except (smtplib.SMTPException, OSError) as exc:
            print(f"Sending the email failed: {exc}", file=sys.stderr)
            email_ok = False
    elif email:
        print(f"Email for {week['week_id']} already sent at {week['emailed_at']}. Use --force to resend.", file=sys.stderr)

    ideas_path.write_text(json.dumps(store, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{week['week_id']}: {len(week['ideas'])} ideas -> {ideas_path}", file=sys.stderr)
    return week, email_ok


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=DATA_DIR)
    ap.add_argument("--email", action="store_true", help="send the weekly email (once per week)")
    ap.add_argument("--force", action="store_true", help="regenerate this week's ideas and resend")
    ap.add_argument("--preview", type=Path, help="write the email HTML to this file")
    args = ap.parse_args(argv)
    week, email_ok = run(args.data, email=args.email, force=args.force, preview=args.preview)
    return 0 if week and email_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
