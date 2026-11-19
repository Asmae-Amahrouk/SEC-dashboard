/* SEC Pulse – weekly blog ideas page. Reads data/ideas.json (scraper/weekly_ideas.py). */
(() => {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const AREA_LABEL = { cyber: "Cybersecurity", ai: "AI", drp: "DRP & resilience" };
  let STORE = null, area = "all";

  const el = (tag, attrs = {}, ...children) => {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === "class") n.className = v;
      else if (k === "text") n.textContent = v;
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v);
    }
    for (const c of children.flat()) if (c != null) n.append(c.nodeType ? c : document.createTextNode(String(c)));
    return n;
  };
  const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : "#");
  const link = (url, text) => el("a", { href: safeUrl(url), target: "_blank", rel: "noopener noreferrer", text });

  function asMarkdown(idea) {
    return [`# ${idea.title}`, "", `**Why now:** ${idea.why_now}`, "", `**Angle:** ${idea.angle}`, "", "## Outline",
      ...idea.outline.map((s, i) => `${i + 1}. ${s}`), "", "## Sources",
      ...idea.sources.map((s) => `- [${s.title}](${s.url}) (${s.source})`)].join("\n");
  }

  function renderWeek(week) {
    const s = week.summary;
    const head = $("#week-head");
    head.replaceChildren(
      el("div", {}, el("div", { class: "kicker", text: `Week ${week.week_id.split("-W")[1]} · ${week.label}` }),
        el("h2", { text: `${week.ideas.length} blog ideas from this week's news` })),
      el("div", { class: "facts" },
        el("div", { class: "fact" }, el("b", { text: s.stories }), el("span", { text: "stories this week" })),
        el("div", { class: "fact" }, el("b", { text: s.by_area.cyber }), el("span", { text: "cybersecurity" })),
        el("div", { class: "fact" }, el("b", { text: s.by_area.ai }), el("span", { text: "AI" })),
        el("div", { class: "fact" }, el("b", { text: s.by_area.drp }), el("span", { text: "resilience / DRP" }))),
      s.rising?.length ? el("ul", {}, s.rising.map((r) => el("li", {}, "Rising theme: ", el("b", { text: r.theme }), ` (${r.this_week} stories, ${r.trend.toLowerCase()})`))) : null);

    const box = $("#ideas");
    const ideas = week.ideas.filter((i) => area === "all" || i.area === area);
    box.replaceChildren(...(ideas.length ? ideas.map((idea) => {
      const copyBtn = el("button", { type: "button", text: "Copy as Markdown" });
      copyBtn.addEventListener("click", async () => {
        try { await navigator.clipboard.writeText(asMarkdown(idea)); copyBtn.textContent = "Copied ✓"; }
        catch (e) { copyBtn.textContent = "Copy failed"; }
        setTimeout(() => (copyBtn.textContent = "Copy as Markdown"), 1800);
      });
      return el("article", { class: "idea", "data-area": idea.area },
        el("div", { class: "label" }, `Idea ${idea.number} of ${week.ideas.length}`,
          el("span", { class: "area" }, el("i", { class: `dot ${idea.area}` }), AREA_LABEL[idea.area]),
          el("span", { class: "trend", text: idea.trend.label })),
        el("h3", { text: idea.title }),
        el("p", {}, el("b", { text: "Why now: " }), idea.why_now),
        el("p", {}, el("b", { text: "Your angle: " }), idea.angle),
        el("h4", { text: "Suggested outline" }), el("ol", {}, idea.outline.map((s) => el("li", { text: s }))),
        el("h4", { text: "Read first" }), el("ul", {}, idea.sources.map((s) => el("li", {}, link(s.url, s.title), " ", el("span", { class: "src", text: `· ${s.source}` })))),
        el("p", { class: "small" }, el("b", { text: "Best for: " }), idea.audience),
        el("div", { class: "actions" }, copyBtn));
    }) : [el("p", { class: "empty-state", text: "No ideas in this area this week." })]));

    $("#top-stories").replaceChildren(...s.top_stories.map((a) => el("li", {}, link(a.url, a.title), el("span", { class: "muted small", text: ` · ${a.source}` }))));
  }

  function current() {
    return STORE.weeks.find((w) => w.week_id === $("#week").value) || STORE.weeks[0];
  }

  async function init() {
    $("#theme-toggle").addEventListener("click", () => {
      const next = getComputedStyle(document.documentElement).colorScheme === "dark" ? "light" : "dark";
      document.documentElement.dataset.theme = next;
      try { localStorage.setItem("sec-theme", next); } catch (e) { /* ignore */ }
    });
    $("#area").addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      area = b.dataset.area;
      $("#area").querySelectorAll("button").forEach((x) => x.classList.toggle("active", x === b));
      if (STORE) renderWeek(current());
    });
    $("#week").addEventListener("change", () => renderWeek(current()));
    try {
      const r = await fetch("data/ideas.json", { cache: "no-cache" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      STORE = await r.json();
      if (!STORE.weeks?.length) throw new Error("no weeks yet");
      $("#week").replaceChildren(...STORE.weeks.map((w) => el("option", { value: w.week_id, text: `Week ${w.week_id.split("-W")[1]}: ${w.label}` })));
      renderWeek(STORE.weeks[0]);
    } catch (err) {
      $("#week-head").replaceChildren(el("h2", { text: "No blog ideas yet" }),
        el("p", { class: "muted", text: "Ideas are generated every Monday by the “Weekly blog ideas” workflow (or run python scraper/weekly_ideas.py)." }));
      $("#week").closest("label").hidden = true;
    }
  }
  init();
})();
