/* SEC Pulse dashboard. Reads data/news.json (written by scraper/fetch_news.py). */
(() => {
  "use strict";

  // ---------- Static vocab (mirrors scraper/classify.py) ----------
  const CATS = ["cyber", "ai", "tech"];
  const CAT_LABEL = { cyber: "Cybersecurity", ai: "AI", tech: "IT / Tech", drp: "Resilience / DRP" };
  const SEVS = ["critical", "high", "medium", "low", "info"];
  const SEV_RANK = { critical: 4, high: 3, medium: 2, low: 1, info: 0 };
  const SEV_LABEL = { critical: "Critical", high: "High", medium: "Medium", low: "Low", info: "Informational" };
  const SEV_HEAT = { critical: 8, high: 4, medium: 2, low: 1, info: 0 };
  const TOPICS = {
    ransomware: ["cyber", "Ransomware"], breach: ["cyber", "Data breach / leak"], vulnerability: ["cyber", "Vulnerability"],
    zeroday: ["cyber", "Zero-day / exploited"], malware: ["cyber", "Malware"], phishing: ["cyber", "Phishing / social eng."],
    apt: ["cyber", "Nation-state / APT"], incident: ["cyber", "Cyberattacks & incidents"], ddos: ["cyber", "DDoS"], supplychain: ["cyber", "Supply chain"],
    fraud: ["cyber", "Crypto / fraud"], lawenforcement: ["cyber", "Arrests & takedowns"],
    infrastructure: ["cyber", "Critical infrastructure"], identity: ["cyber", "Identity & access"],
    privacy: ["cyber", "Privacy & regulation"],
    llm: ["ai", "LLMs & generative AI"], aisecurity: ["ai", "AI security & safety"], agents: ["ai", "AI agents"],
    aipolicy: ["ai", "AI policy & regulation"], aibusiness: ["ai", "AI business & funding"],
    airesearch: ["ai", "Models & research"], compute: ["ai", "Chips & compute"],
    outage: ["drp", "Outages & downtime"], backup: ["drp", "Backup & data protection"],
    recovery: ["drp", "Disaster recovery & IR"], continuity: ["drp", "Business continuity & resilience"], cloud: ["tech", "Cloud & infrastructure"], platforms: ["tech", "OS & platforms"],
    bigtech: ["tech", "Big Tech"], regulation: ["tech", "Tech policy & antitrust"],
  };
  const STOPWORDS = new Set(("a about above after again against all also am an and any are as at be because been before being below " +
    "between both but by can could did do does doing down during each few for from further had has have having he her here hers " +
    "him his how i if in into is it its itself just me more most my no nor not now of off on once only or other our ours out over " +
    "own same she should so some such than that the their them then there these they this those through to too under until up " +
    "very was we were what when where which while who whom why will with you your new says said say how why what update updates " +
    "week weekly report reports could would use used using via vs get gets got make makes made one two three first last year years " +
    "day days time just like now news may might can't won't it's here's what's still back amid across top best big more less " +
    "company companies firm firms people users user million billion data security cyber attack attacks hackers hacker " +
    "jan feb mar apr jun jul aug sep sept oct nov dec january february march april june july august september october " +
    "november december monday tuesday wednesday thursday friday saturday sunday another warns warn warning ceo flaw flaws " +
    "says new latest recap critical code access attackers").split(/\s+/));

  const PAGE_SIZE = 25;
  const $ = (sel) => document.querySelector(sel);
  const state = { range: 1, cat: "all", sev: "", country: null, topic: null, source: null, day: null, q: "", metric: "mentions", shown: PAGE_SIZE };
  let drawerFocus = null; // which click opened the drawer: {type, key}
  let DATA = null, ARTICLES = [], ANCHOR = Date.now(), WORLD = null, NAMES = {}, timelineChart = null;

  // ---------- Helpers ----------
  const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const fmt = (n) => n.toLocaleString("en-US");
  const el = (tag, attrs = {}, ...children) => {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === "class") node.className = v;
      else if (k === "text") node.textContent = v;
      else if (k === "style") node.style.cssText = v;
      else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v);
    }
    for (const c of children.flat()) if (c != null) node.append(c.nodeType ? c : document.createTextNode(String(c)));
    return node;
  };
  const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : "#");
  const countryName = (code) => NAMES[code] || code;
  const timeAgo = (iso) => {
    const s = Math.max(0, (Date.now() - Date.parse(iso)) / 1000);
    if (s < 3600) return `${Math.max(1, Math.round(s / 60))}m ago`;
    if (s < 86400) return `${Math.round(s / 3600)}h ago`;
    const d = Math.round(s / 86400);
    return d === 1 ? "yesterday" : `${d}d ago`;
  };
  const rangeLabel = () => (state.range === 1 ? "24 hours" : `${state.range} days`);
  const sevIcon = (sev) => {
    const paths = {
      critical: "M8 1.5 15 14.5H1z M8 6v4 M8 12v.5",
      high: "M8 1.5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13z M8 4.5v4.5 M8 11v.5",
      medium: "M2 2h12v12H2z M8 5v4 M8 11v.5",
      low: "M8 2 14 8 8 14 2 8z",
      info: "M8 2a6 6 0 1 0 0 12A6 6 0 0 0 8 2z",
    };
    const [shape, ...marks] = paths[sev].split(" M");
    const svg = `<svg viewBox="0 0 16 16" aria-hidden="true"><path d="${shape}" fill="currentColor"/>${marks.map((m) =>
      `<path d="M${m}" stroke="${sev === "medium" ? "#0b0b0b" : "#fff"}" stroke-width="1.8" stroke-linecap="round"/>`).join("")}</svg>`;
    const span = el("span", { class: `sev ${sev}` });
    span.innerHTML = svg; // static markup only
    span.append(SEV_LABEL[sev]);
    return span;
  };

  // ---------- Filtering ----------
  function matches(a, { from, to, skip = [] }) {
    const t = Date.parse(a.published);
    if (t < from || t > to) return false;
    if (!skip.includes("cat") && state.cat !== "all" && (state.cat === "drp" ? !a.drp : a.category !== state.cat)) return false;
    if (!skip.includes("day") && state.day && (t < state.day.from || t >= state.day.to)) return false;
    if (!skip.includes("sev") && state.sev && SEV_RANK[a.severity] < SEV_RANK[state.sev]) return false;
    if (!skip.includes("country") && state.country && !a.countries.includes(state.country)) return false;
    if (!skip.includes("topic") && state.topic && !a.topics.includes(state.topic)) return false;
    if (!skip.includes("source") && state.source && a.source_id !== state.source) return false;
    if (state.q) {
      const hay = a._hay || (a._hay = [a.title, a.summary, a.source, ...(a.cves || []), ...(a.actors || []),
        ...a.countries.map(countryName)].join(" ").toLowerCase());
      if (!state.q.split(/\s+/).every((w) => hay.includes(w))) return false;
    }
    return true;
  }
  const windowNow = () => ({ from: ANCHOR - state.range * 864e5, to: ANCHOR + 36e5 });
  const windowPrev = () => ({ from: ANCHOR - 2 * state.range * 864e5, to: ANCHOR - state.range * 864e5 });
  const select = (opts = {}) => ARTICLES.filter((a) => matches(a, { ...windowNow(), ...opts }));
  const hasPrev = () => ANCHOR - 2 * state.range * 864e5 >= ANCHOR - (DATA.window_days || 30) * 864e5;

  function countBy(list, key) {
    const m = new Map();
    for (const a of list) {
      const vals = typeof key === "function" ? key(a) : a[key];
      for (const v of Array.isArray(vals) ? vals : [vals]) if (v != null) m.set(v, (m.get(v) || 0) + 1);
    }
    return [...m.entries()].sort((x, y) => y[1] - x[1]);
  }

  // ---------- Rendering ----------
  function render() {
    if (!DATA || !ARTICLES.length) return;
    const list = select();
    renderChips();
    renderBriefing(list);
    renderKpis(list);
    renderMap();
    renderCountries();
    renderTimeline(list);
    renderSeverity();
    renderSources(list);
    renderTopicList("#threats", "cyber");
    renderTopicList("#ai-topics", "ai");
    renderTopicList("#drp-topics", "drp");
    renderClouds(list);
    renderStories(list);
    renderDrawer(list);
    writeHash();
  }

  function renderChips() {
    const box = $("#active-filters");
    box.replaceChildren();
    const add = (label, clear) => box.append(el("span", { class: "chip" }, label,
      el("button", { type: "button", "aria-label": `Remove filter ${label}`, onclick: () => { clear(); state.shown = PAGE_SIZE; render(); }, text: "×" })));
    if (state.country) add(`📍 ${countryName(state.country)}`, () => (state.country = null));
    if (state.topic) add(`# ${TOPICS[state.topic]?.[1] || state.topic}`, () => (state.topic = null));
    if (state.source) add(`📰 ${sourceName(state.source)}`, () => (state.source = null));
    if (state.day) add(`🕒 ${dayLabel(state.day)}`, () => (state.day = null));
    if (state.country || state.topic || state.source || state.day || state.q || state.sev || state.cat !== "all") {
      box.append(el("button", { type: "button", class: "chip", onclick: clearAll, text: "Clear all" }));
    }
  }
  const sourceName = (id) => DATA.sources.find((s) => s.id === id)?.name || id;
  function dayLabel(d) {
    const from = new Date(d.from);
    return d.to - d.from <= 36e5
      ? `${from.toLocaleDateString([], { month: "short", day: "numeric" })}, ${from.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`
      : from.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });
  }
  function clearAll() {
    Object.assign(state, { cat: "all", sev: "", country: null, topic: null, source: null, day: null, q: "", shown: PAGE_SIZE });
    closeDrawer();
    syncControls();
    render();
  }

  function renderBriefing(list) {
    const box = $("#briefing");
    box.replaceChildren();
    const sec = list.filter((a) => a.category === "cyber");
    const crit = list.filter((a) => a.severity === "critical");
    const topThreat = countBy(sec, "topics").filter(([t]) => TOPICS[t]?.[0] === "cyber")[0];
    const topAi = countBy(list.filter((a) => a.category === "ai"), "topics").filter(([t]) => TOPICS[t]?.[0] === "ai")[0];
    const topCountry = countBy(list, "countries")[0];
    const topActor = countBy(list, "actors")[0];
    const parts = [];
    const b = (t) => el("strong", { text: t });
    parts.push("In the last ", rangeLabel(), ": ", b(fmt(list.length)), " stories");
    if (crit.length) parts.push(", ", b(`${crit.length} critical`));
    parts.push(". ");
    if (topThreat) parts.push("Top threat theme is ", b(TOPICS[topThreat[0]][1]), ` (${topThreat[1]}). `);
    if (topActor) parts.push("Most-named actor: ", b(topActor[0]), ". ");
    if (topCountry) parts.push("Most-mentioned country: ", b(countryName(topCountry[0])), ". ");
    if (topAi) parts.push("In AI, the buzz is about ", b(TOPICS[topAi[0]][1]), ".");
    if (!list.length) parts.splice(0, parts.length, "No stories match these filters. Try a wider time range.");
    box.append(el("span", { class: "badge", text: "Briefing" }), el("p", {}, ...parts));
  }

  function renderKpis(list) {
    const prev = hasPrev() ? ARTICLES.filter((a) => matches(a, windowPrev())) : null;
    const defs = [
      { label: "Stories", fn: (l) => l.length, tone: "neutral" },
      { label: "Critical + high", fn: (l) => l.filter((a) => SEV_RANK[a.severity] >= 3).length, dot: "var(--sev-critical)" },
      { label: "Exploited / 0-days", fn: (l) => l.filter((a) => a.topics.includes("zeroday")).length, dot: "var(--sev-high)" },
      { label: "Unique CVEs", fn: (l) => new Set(l.flatMap((a) => a.cves || [])).size },
      { label: "Countries in the news", fn: (l) => new Set(l.flatMap((a) => a.countries)).size, tone: "neutral" },
      { label: "AI × Security", fn: (l) => l.filter((a) => a.crossover).length, dot: "var(--series-ai)", tone: "neutral" },
    ];
    const box = $("#kpis");
    box.replaceChildren();
    for (const d of defs) {
      const v = d.fn(list);
      let delta = el("div", { class: "delta", text: `in the last ${rangeLabel()}` });
      if (prev) {
        const p = d.fn(prev);
        const diff = v - p;
        const cls = `${diff > 0 ? "up" : "down"}${d.tone === "neutral" ? " neutral" : ""}`;
        const txt = p === 0 ? (v === 0 ? "no change" : "new this period") : `${diff >= 0 ? "+" : ""}${Math.round((diff / p) * 100)}%`;
        delta = el("div", { class: "delta" }, diff === 0 || p === 0 ? el("span", { text: txt }) : el("span", { class: cls, text: `${diff > 0 ? "▲" : "▼"} ${txt}` }),
          ` vs prior ${state.range === 1 ? "24h" : state.range + "d"}`);
      }
      box.append(el("div", { class: "kpi" },
        el("div", { class: "label" }, d.dot ? el("i", { class: "dot", style: `background:${d.dot}` }) : null, d.label),
        el("div", { class: "value", text: fmt(v) }), delta));
    }
  }

  // ---------- Map ----------
  function countryMetric() {
    const list = select({ skip: ["country"] });
    const m = new Map();
    for (const a of list) {
      const w = state.metric === "heat" ? SEV_HEAT[a.severity] : 1;
      if (!w) continue;
      for (const c of a.countries) m.set(c, (m.get(c) || 0) + w);
    }
    return m;
  }

  function renderMap() {
    if (!WORLD) return;
    const box = $("#map");
    const width = box.clientWidth || 800;
    const height = Math.round(width / 1.9);
    const values = countryMetric();
    const max = Math.max(1, ...values.values());
    const steps = [1, 2, 3, 4, 5, 6].map((i) => cssVar(`--seq-${i}`));
    const bin = (v) => Math.min(5, Math.floor((Math.log1p(v) / Math.log1p(max)) * 6 - 1e-9));
    const color = (v) => (v ? steps[bin(v)] : cssVar("--seq-0"));

    const projection = d3.geoNaturalEarth1().fitExtent([[4, 4], [width - 4, height - 4]], { type: "Sphere" });
    const path = d3.geoPath(projection);
    const svg = d3.select(box).selectAll("svg").data([0]).join("svg").attr("viewBox", `0 0 ${width} ${height}`);
    svg.selectAll("path.sphere").data([{ type: "Sphere" }]).join("path").attr("class", "sphere").attr("d", path);
    const tip = $("#tooltip");
    svg.selectAll("path.country")
      .data(WORLD.features.filter((f) => f.properties.name !== "Antarctica"), (f) => f.properties.name)
      .join("path")
      .attr("class", (f) => `country${f.id === state.country ? " selected" : ""}`)
      .attr("d", path)
      .attr("fill", (f) => color(values.get(f.id) || 0))
      .on("mousemove", (ev, f) => {
        const v = values.get(f.id) || 0;
        tip.replaceChildren(el("strong", { text: NAMES[f.id] || f.properties.name }),
          el("div", { class: "row" }, state.metric === "heat" ? "Threat heat" : "Stories", el("b", { text: fmt(v) })),
          v ? el("div", { class: "row" }, "Click to filter", "") : null);
        showTip(ev);
      })
      .on("mouseleave", hideTip)
      .on("click", (_, f) => toggleCountry(f.id));

    const legend = $("#map-legend");
    legend.replaceChildren(el("span", { text: state.metric === "heat" ? "Lower heat" : "Fewer" }),
      el("span", { class: "ramp" }, el("span", { style: `background:${cssVar("--seq-0")}`, title: "None" }), ...steps.map((s) => el("span", { style: `background:${s}` }))),
      el("span", { text: `${state.metric === "heat" ? "Higher" : "More"} (max ${fmt(max)})` }));
    $("#map-caption").textContent = state.metric === "heat"
      ? "Severity-weighted security stories (critical = 8, high = 4, medium = 2, low = 1)."
      : "Countries mentioned in stories, including attributed threat-actor origins. Click a country to filter.";
  }

  function showTip(ev) {
    const tip = $("#tooltip");
    tip.hidden = false;
    const r = tip.getBoundingClientRect();
    let x = ev.clientX + 14, y = ev.clientY + 14;
    if (x + r.width > innerWidth - 8) x = ev.clientX - r.width - 14;
    if (y + r.height > innerHeight - 8) y = ev.clientY - r.height - 14;
    tip.style.left = `${x}px`;
    tip.style.top = `${y}px`;
  }
  const hideTip = () => ($("#tooltip").hidden = true);
  const toggleCountry = (code) => focus("country", code);

  // Set (or clear, when clicked again) one drill-down filter, then show its stories in the drawer.
  function focus(type, key) {
    const same = state[type] != null && JSON.stringify(state[type]) === JSON.stringify(key);
    state[type] = same ? null : key;
    state.shown = PAGE_SIZE;
    drawerFocus = same ? null : { type, key };
    if (same) closeDrawer(false);
    render();
    if (!same) openDrawer();
  }

  // ---------- Bar lists ----------
  function barList(target, rows, { onClick, isActive, colorOf, empty = "Nothing yet" }) {
    const box = $(target);
    box.replaceChildren();
    if (!rows.length) { box.append(el("li", { class: "empty", text: empty })); return; }
    const max = rows[0].total;
    for (const r of rows) {
      const track = el("div", { class: "track" });
      for (const [k, v] of r.parts) {
        if (!v) continue;
        track.append(el("span", { style: `width:${(v / max) * 100}%;background:${colorOf(k)}`, title: `${CAT_LABEL[k] || k}: ${v}` }));
      }
      box.append(el("li", {
        class: isActive(r.key) ? "active" : "", tabindex: "0", role: "button",
        onclick: () => onClick(r.key), onkeydown: (e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onClick(r.key)),
      }, el("span", { class: "name", text: r.label }), el("span", { class: "count", text: fmt(r.total) }), track));
    }
  }
  const byCategory = (list) => CATS.map((c) => [c, list.filter((a) => a.category === c).length]);
  const catColor = (c) => cssVar(`--series-${c}`);

  function renderCountries() {
    const list = select({ skip: ["country"] });
    const rows = countBy(list, "countries").slice(0, 12).map(([code, total]) => ({
      key: code, label: countryName(code), total, parts: byCategory(list.filter((a) => a.countries.includes(code))),
    }));
    barList("#countries", rows, { onClick: toggleCountry, isActive: (k) => k === state.country, colorOf: catColor, empty: "No locations detected" });
  }

  function renderTopicList(target, cat) {
    const list = select({ skip: ["topic"] });
    const rows = countBy(list, "topics").filter(([t]) => TOPICS[t]?.[0] === cat).slice(0, 10).map(([t, total]) => {
      const sub = list.filter((a) => a.topics.includes(t));
      return cat === "cyber"
        ? { key: t, label: TOPICS[t][1], total, parts: SEVS.map((s) => [s, sub.filter((a) => a.severity === s).length]) }
        : { key: t, label: TOPICS[t][1], total, parts: byCategory(sub) };
    });
    barList(target, rows, {
      onClick: (k) => focus("topic", k),
      isActive: (k) => k === state.topic,
      colorOf: (k) => (SEVS.includes(k) ? cssVar(`--sev-${k}`) : catColor(k)),
    });
  }

  function renderSources(list) {
    const rows = countBy(list, "source_id").slice(0, 8).map(([id, total]) => {
      const src = DATA.sources.find((s) => s.id === id);
      return { key: id, label: src?.name || id, total, parts: byCategory(list.filter((a) => a.source_id === id)) };
    });
    barList("#sources-top", rows, {
      onClick: (k) => focus("source", k),
      isActive: (k) => k === state.source, colorOf: catColor,
    });
  }

  function renderSeverity() {
    const list = select({ skip: ["sev"] }).filter((a) => a.severity !== "info");
    const counts = SEVS.slice(0, 4).map((s) => [s, list.filter((a) => a.severity === s).length]);
    const total = list.length || 1;
    const bar = $("#severity-bar");
    bar.replaceChildren(...counts.filter(([, n]) => n).map(([s, n]) =>
      el("span", {
        style: `flex:${n / total};background:var(--sev-${s})`, title: `${SEV_LABEL[s]}: ${n}. Click to see these stories`,
        class: state.sev && state.sev !== s ? "dim" : null, onclick: () => focusSeverity(s),
      })));
    if (!list.length) bar.append(el("span", { style: "flex:1;background:var(--grid)" }));
    const leg = $("#severity-legend");
    leg.replaceChildren(...counts.map(([s, n]) => el("li", {
      title: `Show ${SEV_LABEL[s].toLowerCase()} and above`,
      onclick: () => focusSeverity(s),
    }, sevIcon(s), el("span", { class: "n", text: `${fmt(n)} · ${Math.round((n / total) * 100)}%` }))));
  }

  function focusSeverity(s) {
    const same = state.sev === s;
    state.sev = same ? "" : s;
    $("#severity").value = ["critical", "high", "medium"].includes(state.sev) ? state.sev : "";
    drawerFocus = same ? null : { type: "sev", key: s };
    state.shown = PAGE_SIZE;
    if (same) closeDrawer(false);
    render();
    if (!same) openDrawer();
  }

  // ---------- Timeline ----------
  function renderTimeline(list) {
    const hourly = state.range === 1;
    const bucketMs = hourly ? 36e5 : 864e5;
    const n = hourly ? 24 : state.range;
    const end = hourly ? Math.ceil(ANCHOR / 36e5) * 36e5 : (() => { const d = new Date(ANCHOR); d.setHours(24, 0, 0, 0); return d.getTime(); })();
    const start = end - n * bucketMs;
    const labels = [], buckets = CATS.map(() => new Array(n).fill(0));
    const bounds = [];
    for (let i = 0; i < n; i++) {
      const d = new Date(start + i * bucketMs);
      bounds.push({ from: start + i * bucketMs, to: start + (i + 1) * bucketMs });
      labels.push(hourly ? d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : d.toLocaleDateString([], { month: "short", day: "numeric" }));
    }
    const tlList = select({ skip: ["day"] });
    for (const a of tlList) {
      const i = Math.floor((Date.parse(a.published) - start) / bucketMs);
      if (i >= 0 && i < n) buckets[CATS.indexOf(a.category)][i]++;
    }
    const cats = state.cat === "all" || state.cat === "drp" ? CATS : [state.cat];
    $("#timeline-caption").textContent = `${hourly ? "Stories per hour" : "Stories per day"} · last ${rangeLabel()} · click a bar to see its stories`;
    $("#timeline-legend").replaceChildren(...cats.map((c) => el("span", {}, el("i", { class: `dot ${c}` }), CAT_LABEL[c])));

    const surface = cssVar("--surface");
    const datasets = cats.map((c) => {
      const idx = CATS.indexOf(c);
      return {
        label: CAT_LABEL[c], data: buckets[idx], borderColor: surface,
        backgroundColor: (ctx) => (state.day && bounds[ctx.dataIndex]?.from !== state.day.from ? `${catColor(c)}55` : catColor(c)),
        borderWidth: { top: 2, bottom: 0, left: 0, right: 0 }, borderSkipped: false, maxBarThickness: 28,
        borderRadius: (ctx) => {
          const later = cats.slice(cats.indexOf(c) + 1).some((o) => buckets[CATS.indexOf(o)][ctx.dataIndex] > 0);
          return later ? 0 : { topLeft: 4, topRight: 4 };
        },
      };
    });
    const grid = cssVar("--grid"), muted = cssVar("--muted"), text = cssVar("--text");
    const options = {
      responsive: true, maintainAspectRatio: false, animation: { duration: 250 },
      interaction: { mode: "index", intersect: false },
      onHover: (evt, els) => { evt.native.target.style.cursor = els.length ? "pointer" : "default"; },
      // Defer: focusing re-renders and destroys this chart, which must not happen inside its own event handler.
      onClick: (evt, els) => { if (els.length) { const slot = bounds[els[0].index]; setTimeout(() => focus("day", slot)); } },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: surface, titleColor: text, bodyColor: text, borderColor: cssVar("--axis"), borderWidth: 1,
          padding: 10, boxPadding: 4, usePointStyle: true,
          callbacks: { footer: (items) => `Total: ${items.reduce((s, i) => s + i.parsed.y, 0)}` },
        },
      },
      scales: {
        x: { stacked: true, grid: { display: false }, border: { color: cssVar("--axis") }, ticks: { color: muted, maxRotation: 0, autoSkipPadding: 12, font: { size: 11 } } },
        y: { stacked: true, beginAtZero: true, grid: { color: grid }, border: { display: false }, ticks: { color: muted, precision: 0, font: { size: 11 } } },
      },
    };
    if (timelineChart) timelineChart.destroy();
    timelineChart = new Chart($("#timeline"), { type: "bar", data: { labels, datasets }, options });
  }

  // ---------- Clouds ----------
  function trendingTerms(list) {
    const counts = new Map(), casing = new Map();
    for (const a of list) {
      const seen = new Set();
      for (const raw of a.title.split(/[^\p{L}\p{N}$'-]+/u)) {
        const w = raw.replace(/^['-]+|['-]+$/g, "").replace(/'s$/i, "");
        const k = w.toLowerCase();
        if (k.length < 3 || STOPWORDS.has(k) || /^\d+$/.test(k) || seen.has(k)) continue;
        seen.add(k);
        counts.set(k, (counts.get(k) || 0) + 1);
        if (!casing.has(k) || /^[A-Z]/.test(w)) casing.set(k, w);
      }
    }
    return [...counts.entries()].filter(([, n]) => n >= 2).sort((a, b) => b[1] - a[1]).slice(0, 22).map(([k, n]) => [casing.get(k), n]);
  }

  function cloud(target, items, empty) {
    const box = $(target);
    box.replaceChildren();
    if (!items.length) { box.append(el("span", { class: "none", text: empty })); return; }
    for (const [label, n] of items) {
      box.append(el("button", { type: "button", class: "tag", onclick: () => setSearch(label) }, label, el("span", { class: "n", text: n })));
    }
  }

  function renderClouds(list) {
    cloud("#trending", trendingTerms(list), "Not enough stories yet");
    cloud("#actors", countBy(list, "actors").slice(0, 14), "No named threat actors");
    cloud("#cves", countBy(list, "cves").slice(0, 12), "No CVEs mentioned");
  }

  function setSearch(term) {
    const input = $("#search");
    input.value = state.q === term.toLowerCase() ? "" : term;
    state.q = input.value.trim().toLowerCase();
    state.shown = PAGE_SIZE;
    render();
  }

  // ---------- Stories ----------
  function storyItem(a) {
    const meta = el("div", { class: "meta" });
    if (a.severity !== "info") meta.append(sevIcon(a.severity));
    meta.append(el("span", { class: "cat" }, el("i", { class: `dot ${a.category}` }), CAT_LABEL[a.category]));
    meta.append(el("span", { text: a.source }));
    if (a.also_in?.length) meta.append(el("span", { title: `Also covered by ${a.also_in.join(", ")}`, text: `+${a.also_in.length} more source${a.also_in.length > 1 ? "s" : ""}` }));
    meta.append(el("time", { datetime: a.published, title: new Date(a.published).toLocaleString(), text: timeAgo(a.published) }));

    const tags = el("div", { class: "tags" });
    for (const t of a.topics.slice(0, 4)) {
      if (TOPICS[t]) tags.append(el("span", { onclick: () => focus("topic", t), text: TOPICS[t][1] }));
    }
    for (const c of a.countries.slice(0, 3)) tags.append(el("span", { onclick: () => toggleCountry(c), text: `📍 ${countryName(c)}` }));
    for (const cve of (a.cves || []).slice(0, 2)) tags.append(el("span", { onclick: () => setSearch(cve), text: cve }));

    return el("li", { class: "story" }, meta,
      el("a", { class: "title", href: safeUrl(a.url), target: "_blank", rel: "noopener noreferrer", text: a.title }),
      a.summary ? el("p", { class: "summary", text: a.summary }) : null,
      tags.childElementCount ? tags : null);
  }

  function renderStories(list) {
    const top = [...list].sort((x, y) => (y.score || 0) - (x.score || 0) || (y.also_in?.length || 0) - (x.also_in?.length || 0)
      || Date.parse(y.published) - Date.parse(x.published)).slice(0, 8);
    $("#top-stories").replaceChildren(...(top.length ? top.map(storyItem) : [el("li", { class: "empty-state", text: "No stories" })]));

    const feed = $("#feed");
    feed.replaceChildren(...(list.length ? list.slice(0, state.shown).map(storyItem)
      : [el("li", { class: "empty-state", text: "No stories match these filters." })]));
    $("#feed-count").textContent = list.length ? `· ${fmt(Math.min(state.shown, list.length))} of ${fmt(list.length)}` : "";
    $("#more").hidden = state.shown >= list.length;
  }

  function renderSourceTable() {
    const ok = DATA.sources.filter((s) => s.ok).length;
    $("#source-summary").textContent = `${ok} of ${DATA.sources.length} feeds fetched on the last run`;
    $("#sources-table tbody").replaceChildren(...DATA.sources.map((s) => el("tr", {},
      el("td", {}, s.site ? el("a", { href: safeUrl(s.site), target: "_blank", rel: "noopener noreferrer", text: s.name }) : s.name),
      el("td", {}, el("span", { class: "cat" }, el("i", { class: `dot ${s.category}` }), " ", CAT_LABEL[s.category])),
      el("td", { class: s.ok ? "status-ok" : "status-err", title: s.error || "", text: s.ok ? "● OK" : `● ${s.error ? s.error.slice(0, 60) : "Error"}` }),
      el("td", { class: "num", text: fmt(ARTICLES.filter((a) => a.source_id === s.id).length) }))));
  }

  // ---------- Wiring ----------
  function bindSeg(id, attr, apply) {
    const group = $(id);
    group.addEventListener("click", (e) => {
      const btn = e.target.closest("button");
      if (!btn) return;
      group.querySelectorAll("button").forEach((b) => b.classList.toggle("active", b === btn));
      apply(btn.dataset[attr]);
      state.shown = PAGE_SIZE;
      render();
    });
  }

  // ---------- Drawer ----------
  function openDrawer() {
    const d = $("#drawer");
    d.classList.add("open");
    d.setAttribute("aria-hidden", "false");
    $("#drawer-backdrop").hidden = false;
    renderDrawer(select());
    d.focus({ preventScroll: true });
  }
  function closeDrawer(rerender = false) {
    const d = $("#drawer");
    if (!d.classList.contains("open")) return;
    d.classList.remove("open");
    d.setAttribute("aria-hidden", "true");
    $("#drawer-backdrop").hidden = true;
    drawerFocus = null;
    if (rerender) render();
  }

  function renderDrawer(list) {
    if (!$("#drawer").classList.contains("open") || !drawerFocus) return;
    const { type, key } = drawerFocus;
    if (state[type === "sev" ? "sev" : type] == null || state[type === "sev" ? "sev" : type] === "") { closeDrawer(); return; }
    const kickers = { country: "Country", topic: "Topic", source: "Source", day: "Time slot", sev: "Severity" };
    const titles = {
      country: () => `📍 ${countryName(key)}`, topic: () => TOPICS[key]?.[1] || key, source: () => sourceName(key),
      day: () => dayLabel(key), sev: () => `${SEV_LABEL[key]}${key === "critical" ? "" : " and above"}`,
    };
    $("#drawer-kicker").textContent = `${kickers[type]} · ${state.day && type !== "day" ? dayLabel(state.day) : `last ${rangeLabel()}`}`
      + (state.cat !== "all" ? ` · ${CAT_LABEL[state.cat]}` : "");
    $("#drawer-title").textContent = titles[type]();

    const body = $("#drawer-body");
    const crit = list.filter((a) => SEV_RANK[a.severity] >= 3).length;
    const facts = el("div", { class: "facts" },
      el("div", { class: "fact" }, el("b", { text: fmt(list.length) }), el("span", { text: "stories" })),
      el("div", { class: "fact" }, el("b", { text: fmt(crit) }), el("span", { text: "critical + high" })),
      el("div", { class: "fact" }, el("b", { text: fmt(new Set(list.map((a) => a.source_id)).size) }), el("span", { text: "sources" })));
    const section = (title, items, onPick) => items.length ? el("div", {},
      el("h3", { class: "mini-title", text: title }),
      el("div", { class: "cloud" }, items.map(([k, n, label]) => el("button", { type: "button", class: "tag", onclick: () => onPick(k) }, label || k, el("span", { class: "n", text: n }))))) : null;
    const topics = countBy(list, "topics").filter(([t]) => t !== key && TOPICS[t]).slice(0, 8).map(([t, n]) => [t, n, TOPICS[t][1]]);
    const countries = type === "country" ? [] : countBy(list, "countries").slice(0, 8).map(([c, n]) => [c, n, countryName(c)]);
    const sources = type === "source" ? [] : countBy(list, "source_id").slice(0, 6).map(([id, n]) => [id, n, sourceName(id)]);
    const stories = [...list].sort((x, y) => (y.score || 0) - (x.score || 0) || Date.parse(y.published) - Date.parse(x.published));
    body.replaceChildren(...[facts,
      section("Main themes", topics, (t) => { drawerFocus = { type: "topic", key: t }; state.topic = t; render(); }),
      section("Threat actors", countBy(list, "actors").slice(0, 8), setSearch),
      section("Countries", countries, (c) => { drawerFocus = { type: "country", key: c }; state.country = c; render(); }),
      section("Sources", sources, (id) => { drawerFocus = { type: "source", key: id }; state.source = id; render(); }),
      el("div", {}, el("h3", { class: "mini-title", text: `Stories (${fmt(list.length)}), most severe first` }),
        el("ol", { class: "stories" }, stories.length ? stories.slice(0, 60).map(storyItem) : [el("li", { class: "empty-state", text: "No stories" })]),
        list.length > 60 ? el("p", { class: "muted small", text: `Showing 60 of ${fmt(list.length)}. Use the main feed for the rest.` }) : null)]
      .filter(Boolean));
  }

  // ---------- Shareable URL (#range=7&country=276…) ----------
  function writeHash() {
    const p = new URLSearchParams();
    if (state.range !== 1) p.set("range", state.range);
    if (state.cat !== "all") p.set("cat", state.cat);
    if (state.sev) p.set("sev", state.sev);
    if (state.country) p.set("country", state.country);
    if (state.topic) p.set("topic", state.topic);
    if (state.source) p.set("source", state.source);
    if (state.day) p.set("slot", `${state.day.from}-${state.day.to}`);
    if (state.q) p.set("q", state.q);
    if (state.metric !== "mentions") p.set("map", state.metric);
    const hash = p.toString();
    if (hash !== location.hash.slice(1)) history.replaceState(null, "", hash ? `#${hash}` : location.pathname + location.search);
  }
  function readHash() {
    const p = new URLSearchParams(location.hash.slice(1));
    const range = Number(p.get("range"));
    state.range = [1, 7, 30].includes(range) ? range : 1;
    state.cat = ["cyber", "ai", "tech", "drp"].includes(p.get("cat")) ? p.get("cat") : "all";
    state.sev = SEVS.includes(p.get("sev")) ? p.get("sev") : "";
    state.country = /^\d{3}$/.test(p.get("country") || "") ? p.get("country") : null;
    state.topic = TOPICS[p.get("topic")] ? p.get("topic") : null;
    state.source = p.get("source") || null;
    const slot = (p.get("slot") || "").match(/^(\d+)-(\d+)$/);
    state.day = slot ? { from: Number(slot[1]), to: Number(slot[2]) } : null;
    state.q = (p.get("q") || "").toLowerCase().slice(0, 100);
    state.metric = p.get("map") === "heat" ? "heat" : "mentions";
  }
  function syncControls() {
    const mark = (id, attr, val) => $(id).querySelectorAll("button").forEach((b) => b.classList.toggle("active", b.dataset[attr] === String(val)));
    mark("#range", "range", state.range);
    mark("#category", "cat", state.cat);
    mark("#map-metric", "metric", state.metric);
    $("#severity").value = ["critical", "high", "medium"].includes(state.sev) ? state.sev : "";
    $("#search").value = state.q;
  }

  function wire() {
    bindSeg("#range", "range", (v) => { state.range = Number(v); state.day = null; });
    bindSeg("#category", "cat", (v) => (state.cat = v));
    bindSeg("#map-metric", "metric", (v) => (state.metric = v));
    $("#severity").addEventListener("change", (e) => { state.sev = e.target.value; state.shown = PAGE_SIZE; render(); });
    let t;
    $("#search").addEventListener("input", (e) => {
      clearTimeout(t);
      t = setTimeout(() => { state.q = e.target.value.trim().toLowerCase(); state.shown = PAGE_SIZE; render(); }, 180);
    });
    $("#more").addEventListener("click", () => { state.shown += PAGE_SIZE; renderStories(select()); });
    $("#theme-toggle").addEventListener("click", () => {
      const dark = getComputedStyle(document.documentElement).colorScheme === "dark";
      const next = dark ? "light" : "dark";
      document.documentElement.dataset.theme = next;
      try { localStorage.setItem("sec-theme", next); } catch (e) { /* storage unavailable */ }
      render();
    });
    $("#drawer-close").addEventListener("click", () => closeDrawer());
    $("#drawer-backdrop").addEventListener("click", () => closeDrawer());
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });
    addEventListener("hashchange", () => {
      if (!DATA) return;
      readHash();
      syncControls();
      render();
    });
    let rt;
    new ResizeObserver(() => { clearTimeout(rt); rt = setTimeout(renderMap, 120); }).observe($("#map"));
  }

  function showError(msg) {
    $("#updated").textContent = "No data";
    $("#briefing").replaceChildren(el("span", { class: "badge", text: "Setup" }), el("p", {}, msg));
  }

  async function init() {
    readHash();
    syncControls();
    wire();
    try {
      const [news, topo] = await Promise.all([
        fetch("data/news.json", { cache: "no-cache" }).then((r) => { if (!r.ok) throw new Error(`news.json: HTTP ${r.status}`); return r.json(); }),
        fetch("vendor/countries-110m.json").then((r) => r.json()),
      ]);
      DATA = news;
      ARTICLES = (news.articles || []).map((a) => ({ ...a, countries: a.countries || [], topics: a.topics || [] }));
      WORLD = topojson.feature(topo, topo.objects.countries);
      for (const f of WORLD.features) if (f.id) NAMES[f.id] = f.properties.name;
      Object.assign(NAMES, news.country_names || {});
      ANCHOR = Date.parse(news.generated_at) || Date.now();
      if (news.generated_at) {
        const gen = new Date(ANCHOR);
        $("#updated").textContent = `Updated ${timeAgo(news.generated_at)} · ${gen.toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}`;
        $("#updated").title = `Data generated at ${gen.toISOString()}`;
      }
      if (!ARTICLES.length) {
        showError("No stories yet. Run the “Update news” GitHub Action (or python scraper/fetch_news.py) to collect the first batch.");
        renderMap();
        return;
      }
      renderSourceTable();
      render();
    } catch (err) {
      console.error(err);
      showError(`Could not load data/news.json (${err.message}). Serve the docs/ folder over HTTP (python -m http.server -d docs) and run the scraper first.`);
    }
  }

  init();
})();
