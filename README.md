# SEC Pulse: cybersecurity, AI and tech news dashboard

A dashboard you can open each morning to see what's happening in **cybersecurity**, **artificial intelligence** and **IT/tech**. It collects headlines from 24 well-known sources (BleepingComputer, The Hacker News, Krebs, Dark Reading, SecurityWeek, The Record, CISA, MIT Technology Review, The Verge, TechCrunch, Ars Technica and others) and turns them into statistics, a world map and a filterable feed.

## What you get

- **Daily briefing**: one sentence covering story volume, critical items, the top threat theme, the most-named threat actor, the most-mentioned country and the main AI theme.
- **KPI tiles**: stories, critical + high severity, exploited / zero-day items, unique CVEs, countries in the news and AI × Security crossover stories. Each tile compares against the previous period.
- **World map**: a choropleth of country mentions, or *threat heat* (security stories weighted by severity). Click a country to filter everything.
- **Hotspots**: the top countries, broken down by category.
- **Story volume**: stories per hour (24h view) or per day (7/30 days), stacked by category.
- **Security severity**: the critical / high / medium / low split and the most active sources.
- **Threat landscape**: ransomware, breaches, vulnerabilities, zero-days, malware, phishing, APTs, DDoS, supply chain and more.
- **AI radar**: LLMs, AI security & safety, agents, policy, funding, research, chips.
- **Trending terms, threat actors, most-cited CVEs**: click any of them to search.
- **Must-read and latest stories**, with severity, category, source, places and topics on each story.
- **Source health**: which feeds worked on the last run.
- Light/dark mode, phone-friendly layout, no tracking, no backend.

## How it works

```
config/sources.json      list of RSS/Atom feeds (add/remove sources here)
scraper/fetch_news.py    fetches feeds in parallel, dedupes, writes docs/data/*.json
scraper/classify.py      keyword rules: category, topics, severity, CVEs, actors
scraper/countries.py     country gazetteer + threat-actor attribution
scraper/serve.py         Docker entrypoint: web server + refresh timer
Dockerfile, docker-compose.yml
docs/                    the static dashboard (GitHub Pages serves this folder)
.github/workflows/       GitHub Action that refreshes the data every 3 hours
```

The scraper uses only the Python standard library (plus optional `defusedxml` for safer XML parsing). It keeps a rolling **30-day** window in `docs/data/news.json` and a year of daily aggregates in `docs/data/history.json`. No API keys needed. Host it free on GitHub Pages, or run it yourself with Docker.

**How stories get labeled.** Every label comes from transparent keyword rules, not AI:
- *Category*: a story's topics outweigh its source. A ransomware story on TechCrunch counts as Cyber; a ChatGPT story on a tech site counts as AI.
- *Severity* (security stories only): zero-days, active exploitation, nation-state activity, critical CVSS, breaches affecting millions and ransomware push the score up. Non-security stories are "informational".
- *Countries*: country names, demonyms, capitals and key agencies (FBI, CISA, GCHQ…) are matched. Named threat actors add their attributed country (for example Volt Typhoon adds China).

Expect some mislabels. Tune the rules in `scraper/classify.py` and `scraper/countries.py`.

## Set it up (about 5 minutes)

1. **Merge this branch into `main`.** Scheduled GitHub Actions only run from the default branch.
2. **Turn on GitHub Pages**: *Settings → Pages → Build and deployment → Deploy from a branch → `main` / `/docs`*.
3. **Allow the Action to commit**: *Settings → Actions → General → Workflow permissions → Read and write*.
4. **Run it once by hand**: *Actions → Update news → Run workflow*. It refreshes every 3 hours after that.
5. Open `https://<your-username>.github.io/<repo>/` and bookmark it.

## Run with Docker

The image holds both the dashboard and the news collector. It fetches the feeds when it starts and again every 3 hours, and keeps the collected news in a volume.

```bash
docker compose up -d --build        # then open http://localhost:8080
docker compose logs -f              # watch the feed refreshes
docker compose down                 # stop (news is kept in the "news-data" volume)
```

Without Compose:

```bash
docker build -t sec-pulse .
docker run -d --name sec-pulse -p 8080:8080 -v sec-pulse-data:/app/docs/data --restart unless-stopped sec-pulse
```

Settings (environment variables):

| Variable | Default | Meaning |
|---|---|---|
| `PORT` | `8080` | HTTP port inside the container |
| `REFRESH_HOURS` | `3` | Hours between feed refreshes (`0` = only at startup) |
| `WINDOW_DAYS` | `30` | Days of stories to keep |
| `FETCH_ON_START` | `1` | Set to `0` to skip the fetch at startup |
| `ACCESS_LOG` | `0` | Set to `1` to log every HTTP request |

The container runs as a non-root user and exposes `/healthz` for health checks. It turns off directory listings and sends security headers, including a strict Content-Security-Policy. To use your own feed list, mount it: `-v ./config/sources.json:/app/config/sources.json:ro`.

A prebuilt image is published to GitHub Container Registry on every push to `main` (`.github/workflows/docker.yml`):

```bash
docker run -d -p 8080:8080 -v sec-pulse-data:/app/docs/data ghcr.io/<your-username>/sec-dashboard:latest
```

For access from other machines, put it behind a reverse proxy with HTTPS (Caddy, Traefik, nginx). The built-in server is fine for home or LAN use, but it is not built to face the internet directly.

## Run locally

```bash
pip install -r requirements-dev.txt
python scraper/fetch_news.py          # fetch the feeds -> docs/data/news.json
python -m http.server -d docs 8000    # open http://localhost:8000
python -m pytest -q tests             # run the tests
```

Options: `--days 45` keeps a longer window; `--only bleepingcomputer,cisa` fetches selected sources.

## Add a source

Add an entry to `config/sources.json`:

```json
{ "id": "my-feed", "name": "My Feed", "category": "cyber", "url": "https://example.com/feed.xml", "site": "https://example.com" }
```

`category` is the feed's default bucket (`cyber`, `ai` or `tech`). Set `"enabled": false` to pause a feed.

## Ideas for later

- Email or Telegram digest of the day's critical stories
- CISA KEV and NVD feeds for CVSS scores
- Optional LLM summaries and better country/actor extraction
- Watchlists for your own vendors and technologies

## Credits

Headlines and links belong to their publishers; the dashboard only links to the originals. Map data comes from [world-atlas](https://github.com/topojson/world-atlas) (Natural Earth). Charts use [Chart.js](https://www.chartjs.org/) and [D3](https://d3js.org/). All three are vendored in `docs/vendor/`.
