# Prime Video Watcher v2 — multi-region

Weekly agent that detects **new titles** (films + series) added to **Amazon Prime
Video** across several countries. Runs free on **GitHub Actions** (weekly cron)
and publishes a self-updating page on **GitHub Pages** with a **region selector**.

## Architecture

Two data sources, by design:

- **TMDB (primary)** — powers all 7 regions in the dropdown: **US, IT, UK, DE, FR,
  ES, CA**. No country cap, generous rate limits. This is what the page shows.
- **Watchmode (cross-check)** — an official streaming-availability API used to
  *confirm* titles for **US, IT, UK** only. Confirmed titles get a purple
  "WM ✓" badge. The free Watchmode tier allows **only 3 countries**, which is why
  cross-check is limited to those three. The other regions are TMDB-only.

Why two sources: TMDB's per-provider data is community-maintained and occasionally
misses or mislabels availability. Watchmode is a second, independent confirmation
for your priority markets. If the Watchmode key is absent, the tool still works —
it just skips the badges.

## How it works

1. Every **Monday 07:00 UTC**, GitHub Actions runs `watcher.py`.
2. For each region it queries TMDB `/discover` (Prime Video provider, that region).
3. For US/IT/UK it also queries Watchmode and tags confirmed titles.
4. It diffs each region against last week's snapshot (`state.json`) and writes
   `docs/data.json` + `docs/index.html`.
5. GitHub Pages serves the page; the region `<select>` switches between datasets
   already baked into `data.json` (no live API calls from the browser).
6. If there are new titles in US/IT/UK, you get an email digest.

The **first run** takes a baseline snapshot per region (no "new", no email). Real
diffs start from the **second** weekly run.

## Setup (once)

### 1. TMDB key (required)
- Sign up at https://www.themoviedb.org/signup → Settings → API.
- Copy the **API Read Access Token** (starts with `eyJ…`) or the v3 key.

### 2. Watchmode key (optional but recommended)
- Request a free key at https://api.watchmode.com/requestApiKey (no credit card).
- **When it asks which 3 countries, choose US, IT, UK** — must match the tool.
- Free tier = 2,500 requests/month; this tool uses only a handful per week.

### 3. Create the repo & upload files
Keep the structure exactly:
```
watcher.py
.github/workflows/watcher.yml
README.md
```
(`docs/` is created automatically on the first run.)

### 4. Add Secrets (Settings → Secrets and variables → Actions)

| Secret | Required | Value |
|--------|----------|-------|
| `TMDB_API_KEY` | yes | your TMDB token |
| `WATCHMODE_API_KEY` | no | your Watchmode key |
| `SMTP_USER` | no | Gmail address (for email) |
| `SMTP_PASS` | no | Gmail **App Password** (16 chars) |
| `MAIL_TO` | no | recipient(s), comma-separated |

Optional **Variable** (not secret): `PAGE_URL` = your Pages URL, shown as a button
in the email.

### 5. Enable Pages
Settings → Pages → Source: **GitHub Actions**.

### 6. First run
Actions tab → **Prime Video Watcher** → **Run workflow**. When it's green, your
page is at `https://<user>.github.io/<repo>/` (baseline; real diffs next week).

## Customization

| Want | Where | How |
|------|-------|-----|
| Different dropdown regions | `watcher.py` → `REGIONS` | Add/remove country codes (TMDB uses `GB` for UK) |
| Different Watchmode trio | `watcher.py` → `WM_REGIONS` | Must match the 3 countries chosen on the key |
| Change run day/time | `.github/workflows/watcher.yml` → `cron` | UTC cron syntax |
| Subscription only (no ads) | `watcher.py` → `TMDB_PROVIDERS` | set `"9"` |

## Notes

- TMDB uses `GB` for the United Kingdom; Watchmode uses `UK`. The code maps
  between them in `WM_REGIONS` — keep that mapping if you edit regions.
- Attribution for TMDB and Watchmode is included in the page footer per their terms.
- Availability data can lag reality by a day or two on either source.

## Files
- `watcher.py` — multi-region fetch, diff, Watchmode cross-check, page + JSON generation, email
- `.github/workflows/watcher.yml` — weekly cron + Pages deploy
- `README.md` — this guide
