"""Rule-based enrichment: category, topics, severity, countries, CVEs, actors.

Everything here is deterministic keyword matching, so it is fast, free and
explainable. Tune the dictionaries below to change how stories are bucketed.
"""
from __future__ import annotations

import re
from functools import lru_cache

from countries import BLOCKERS, COUNTRIES, THREAT_ACTORS

CATEGORIES = ("cyber", "ai", "tech")

# topic id -> (category, label, regex of keywords)
TOPICS: dict[str, tuple[str, str, str]] = {
    # --- Cybersecurity ---
    "ransomware": ("cyber", "Ransomware", r"ransomware|extortion gang|double extortion|encrypt(?:ed|s) files|ransom (?:note|demand)"),
    "breach": ("cyber", "Data breach / leak", r"data breach|breach(?:ed|es)?\b|data leak|leaked (?:data|database|records)|exposed (?:data|database|records)|stolen data|hack(?:ed)? (?:into|of)|compromised (?:accounts|data|systems)"),
    "vulnerability": ("cyber", "Vulnerability", r"vulnerabilit(?:y|ies)|\bflaws?\b|\bCVE-\d{4}-\d+|security (?:bug|hole|update|patch)|\bpatch(?:es|ed)?\b|\bRCE\b|remote code execution|privilege escalation|authentication bypass|buffer overflow|SQL injection|\bXSS\b"),
    "zeroday": ("cyber", "Zero-day / exploited", r"zero[- ]day|\b0[- ]day|actively exploited|exploited in the wild|in-the-wild exploit|under active (?:attack|exploitation)|mass[- ]exploitation|\bKEV\b|known exploited"),
    "malware": ("cyber", "Malware", r"malware|trojan|infostealer|\bstealer\b|botnet|backdoor|\bRAT\b|spyware|\bwiper\b|\bworm\b|rootkit|\bloader\b|keylogger|cryptominer|malicious (?:app|extension|code)"),
    "phishing": ("cyber", "Phishing / social eng.", r"phishing|smishing|vishing|social engineering|business email compromise|\bBEC\b|scam (?:email|text|call)s?|impersonat(?:e|ing|ion)|fake (?:login|site|website|app)"),
    "apt": ("cyber", "Nation-state / APT", r"(?:Chinese|Russian|Iranian|North Korean|Pro-Russian|state)(?:[- ]linked| state| government)? hackers|\bAPT\s?\d*\b|nation[- ]state|state[- ]sponsored|state[- ]backed|cyber[- ]?espionage|espionage|\bTyphoon\b|\bBlizzard\b|\bSandstorm\b|cyberwar|cyber war"),
    "incident": ("cyber", "Cyberattacks & incidents", r"cyber[- ]?attacks?|cyber incident|security incident|hit by (?:a )?(?:cyber|hack)|systems? (?:offline|down)|halts? (?:production|operations)|disrupt(?:s|ed|ion)? (?:operations|services|production)"),
    "ddos": ("cyber", "DDoS", r"\bDDoS\b|denial[- ]of[- ]service|hacktivis(?:t|m)"),
    "supplychain": ("cyber", "Supply chain", r"supply[- ]chain|malicious (?:package|npm|PyPI|library|update)|\bnpm\b|\bPyPI\b|typosquat|dependency confusion|open[- ]source package"),
    "fraud": ("cyber", "Crypto / fraud", r"crypto(?:currency)? (?:theft|heist|scam|exchange hack)|\bheist\b|fraud|money laundering|scam(?:mers)?\b|pig butchering|drained|wallet drainer"),
    "lawenforcement": ("cyber", "Arrests & takedowns", r"arrest(?:ed|s)?|charged|indict(?:ed|ment)|sentenced|extradit(?:ed|ion)|takedown|taken down|seiz(?:ed|ure)|dismantl(?:ed|es)|Europol|Interpol|Operation [A-Z][a-z]+|pleads? guilty|sanction(?:s|ed)"),
    "infrastructure": ("cyber", "Critical infrastructure", r"critical infrastructure|\bICS\b|\bSCADA\b|\bOT\b (?:security|network)|operational technology|power grid|water (?:utility|facility|treatment)|pipeline|hospital|healthcare (?:provider|system)|energy sector|telecom(?:s|munications)? (?:providers?|networks?|operators?|firms?|companies|giants?)"),
    "identity": ("cyber", "Identity & access", r"credential|password|\bMFA\b|multi-factor|two-factor|\b2FA\b|passkey|authentication|\bOAuth\b|single sign-on|\bSSO\b|session token|account takeover"),
    "privacy": ("cyber", "Privacy & regulation", r"privacy|\bGDPR\b|data protection|surveillance|\bfine[ds]?\b|regulator|compliance|\bNIS2\b|\bDORA\b|lawsuit|class action|disclosure rule"),
    # --- Artificial intelligence ---
    "llm": ("ai", "LLMs & generative AI", r"\bLLMs?\b|large language model|generative AI|\bGenAI\b|chatbot|ChatGPT|\bGPT-?\d|\bClaude\b|\bGemini\b|\bLlama\b|Mistral|DeepSeek|Copilot|foundation model|frontier model|\bQwen\b|\bGrok\b"),
    "aisecurity": ("ai", "AI security & safety", r"prompt injection|jailbreak|deepfake|AI safety|model (?:poisoning|theft|weights)|data poisoning|AI red team|adversarial (?:attack|example)|AI-powered (?:attack|malware|phishing)|AI misuse|alignment|hallucinat"),
    "agents": ("ai", "AI agents", r"\bagentic\b|AI agents?|autonomous agents?|\bMCP\b|Model Context Protocol|computer use|coding agent|agent framework"),
    "aipolicy": ("ai", "AI policy & regulation", r"AI Act|AI regulation|AI law|AI policy|AI governance|executive order on AI|AI bill|AI copyright|copyright lawsuit|AI oversight"),
    "aibusiness": ("ai", "AI business & funding", r"raises \$|funding round|series [A-F]\b|valuation|acquir(?:es|ed|ition)|IPO|\bunicorn\b|startup|revenue|layoffs|partnership"),
    "airesearch": ("ai", "Models & research", r"open[- ](?:source|weight) model|benchmark|\bresearch(?:ers)?\b|paper|reasoning model|multimodal|fine-tun|training (?:run|data)|new model|model release|\bAGI\b"),
    "compute": ("ai", "Chips & compute", r"Nvidia|\bGPUs?\b|\bTPUs?\b|semiconductor|\bchips?\b|data ?cent(?:er|re)s?|\bAMD\b|\bTSMC\b|compute capacity|supercomputer"),
    # --- General IT / tech ---
    "outage": ("tech", "Outages & incidents", r"outage|went down|service disruption|downtime|\bdown for\b|disrupted service"),
    "cloud": ("tech", "Cloud & infrastructure", r"\bcloud\b|\bAWS\b|\bAzure\b|Google Cloud|kubernetes|serverless|\bSaaS\b"),
    "platforms": ("tech", "OS & platforms", r"Windows \d+|\bWindows\b|macOS|\biOS\b|Android|Linux|Chrome(?:OS)?|Firefox|browser|smartphone|iPhone|Pixel"),
    "bigtech": ("tech", "Big Tech", r"\bApple\b|\bGoogle\b|Microsoft|\bMeta\b|Amazon|\bOpenAI\b|Anthropic|\bX Corp\b|TikTok|Samsung"),
    "regulation": ("tech", "Tech policy & antitrust", r"antitrust|competition (?:law|authority)|Digital Markets Act|\bDMA\b|\bDSA\b|regulators?|\bban(?:s|ned)?\b|legislation"),
}

# Severity signals (only meaningful for security stories). weight, regex
SEVERITY_SIGNALS: list[tuple[int, str]] = [
    (6, r"zero[- ]day|\b0[- ]day|actively exploited|exploited in the wild|under active (?:attack|exploitation)|mass[- ]exploitation"),
    (5, r"critical infrastructure|wiper|nation[- ]state|state[- ]sponsored|emergency (?:directive|patch|update)"),
    (4, r"CVSS (?:score of )?(?:9\.\d|10(?:\.0)?)|critical(?:[- ]severity)?(?:\s+[\w-]+){0,3}\s+(?:vulnerabilit|flaws?\b|bugs?\b|RCE)|maximum severity"),
    (4, r"\b\d+(?:\.\d+)? (?:million|billion)\b(?: \w+){0,3} (?:records|users|customers|people|patients|accounts)"),
    (3, r"ransomware|cyber[- ]?attack|halts? (?:production|operations)|(?:Chinese|Russian|Iranian|North Korean) (?:state )?hackers|run (?:arbitrary |malicious )?code|as root|remote code execution|\bRCE\b|backdoor|supply[- ]chain attack|data breach|hospital|power grid|water (?:utility|facility)"),
    (2, r"breach|exploit|hijack|espionage|botnet|stealer|DDoS|malicious package"),
    (1, r"vulnerabilit|flaw|malware|phishing|patch|attack|hack"),
]
SEVERITY_LEVELS = [(9, "critical"), (5, "high"), (2, "medium"), (0, "low")]

CVE_RE = re.compile(r"\bCVE-(\d{4})-(\d{4,7})\b", re.IGNORECASE)


@lru_cache(maxsize=None)
def _topic_patterns() -> dict[str, re.Pattern]:
    return {tid: re.compile(rx, re.IGNORECASE) for tid, (_, _, rx) in TOPICS.items()}


@lru_cache(maxsize=None)
def _severity_patterns() -> list[tuple[int, re.Pattern]]:
    return [(w, re.compile(rx, re.IGNORECASE)) for w, rx in SEVERITY_SIGNALS]


def _phrase_regex(phrases: list[str], flags: int) -> re.Pattern | None:
    if not phrases:
        return None
    # Longest first so alternation prefers "Papua New Guinea" over "Guinea".
    alts = sorted({p for p in phrases}, key=len, reverse=True)
    body = "|".join(re.escape(p) for p in alts)
    # Word-ish boundaries that also work around punctuation such as "U.S.".
    return re.compile(rf"(?<![\w$])(?:{body})(?![\w])", flags)


@lru_cache(maxsize=None)
def _gazetteer():
    """Build (pattern, code) pairs. code None = blocker."""
    entries: list[tuple[re.Pattern, str | None]] = []
    for code, (_, aliases, exact) in COUNTRIES.items():
        if (rx := _phrase_regex(aliases, re.IGNORECASE)) is not None:
            entries.append((rx, code))
        if (rx := _phrase_regex(exact, 0)) is not None:
            entries.append((rx, code))
    entries.append((_phrase_regex(BLOCKERS, re.IGNORECASE), None))
    actor_rx = _phrase_regex(list(THREAT_ACTORS), re.IGNORECASE)
    return entries, actor_rx


def find_countries(text: str) -> list[str]:
    """Return ISO numeric codes mentioned in text (ordered by first mention)."""
    entries, _ = _gazetteer()
    spans: list[tuple[int, int, str | None]] = []
    for rx, code in entries:
        for m in rx.finditer(text):
            spans.append((m.start(), m.end(), code))
    # Longest match wins; drop anything overlapping an accepted span.
    spans.sort(key=lambda s: (-(s[1] - s[0]), s[0]))
    taken: list[tuple[int, int]] = []
    hits: list[tuple[int, str]] = []
    for start, end, code in spans:
        if any(start < e and end > s for s, e in taken):
            continue
        taken.append((start, end))
        if code is not None:
            hits.append((start, code))
    seen: dict[str, None] = {}
    for _, code in sorted(hits):
        seen.setdefault(code, None)
    return list(seen)


def find_actors(text: str) -> list[str]:
    _, actor_rx = _gazetteer()
    canon = {k.lower(): k for k in THREAT_ACTORS}
    out: dict[str, None] = {}
    for m in actor_rx.finditer(text):
        out.setdefault(canon[m.group(0).lower()], None)
    return list(out)


def find_cves(text: str) -> list[str]:
    out: dict[str, None] = {}
    for m in CVE_RE.finditer(text):
        out.setdefault(f"CVE-{m.group(1)}-{m.group(2)}", None)
    return list(out)


def find_topics(text: str) -> list[str]:
    return [tid for tid, rx in _topic_patterns().items() if rx.search(text)]


def score_severity(title: str, body: str, cves: list[str]) -> int:
    score = 0
    for weight, rx in _severity_patterns():
        if rx.search(title):
            score += weight  # headline signals count fully
        elif rx.search(body):
            score += weight // 2
    score += min(len(cves), 3)
    return score


def severity_label(score: int) -> str:
    for threshold, label in SEVERITY_LEVELS:
        if score >= threshold:
            return label
    return "low"


def pick_category(topics: list[str], default: str, title: str) -> str:
    weights = {c: 0.0 for c in CATEGORIES}
    title_topics = set(find_topics(title))
    for tid in topics:
        cat = TOPICS[tid][0]
        weights[cat] += 2.0 if tid in title_topics else 1.0
    # Generic tech topics are weak evidence; the source's own focus is strong.
    weights["tech"] *= 0.6
    weights[default] += 1.5
    best = max(CATEGORIES, key=lambda c: (weights[c], c == default))
    return best


def enrich(title: str, summary: str, default_category: str) -> dict:
    text = f"{title}\n{summary}"
    topics = find_topics(text)
    cves = find_cves(text)
    category = pick_category(topics, default_category, title)
    actors = find_actors(text)
    countries = find_countries(text)
    for actor in actors:
        origin = THREAT_ACTORS.get(actor)
        if origin and origin not in countries:
            countries.append(origin)
    score = score_severity(title, summary, cves) if category == "cyber" or "aisecurity" in topics else 0
    has_cyber = any(TOPICS[t][0] == "cyber" for t in topics if t not in ("privacy", "identity"))
    return {
        "category": category,
        "topics": topics,
        "severity": severity_label(score) if score else "info",
        "score": score,
        "countries": countries,
        "cves": cves,
        "actors": actors,
        "crossover": category == "ai" and has_cyber or category == "cyber" and any(TOPICS[t][0] == "ai" for t in topics if t != "compute"),
    }
