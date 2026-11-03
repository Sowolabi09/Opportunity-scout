# Opportunity Scout 🎓

**Always-on agent for physiology & biomedical scholarships — 100% free stack.**

> Built for a physiology student in Nigeria. Continuously scouts the web for legitimate scholarships, funded MSc/PhD programs, fellowships and internships, verifies them, scores them against your profile, and alerts you within minutes.

[![Worker](https://github.com/YOU/opportunity-scout/actions/workflows/scout.yml/badge.svg)](../../actions)
[![Secret Scan](https://github.com/YOU/opportunity-scout/actions/workflows/secret-scan.yml/badge.svg)](../../actions)

Live dashboard: `https://your-app.streamlit.app` _(replace after deploy)_
Worker status: last run visible in dashboard + `heartbeat.json`

---

## What it does

1. Checks 30+ sources every 10–15 min (fast RSS) and every few hours (slow university pages)
2. Deduplicates, cheap-filters, then extracts structured data with Gemini Flash-Lite (free)
3. Verifies legitimacy → `VERIFIED / UNVERIFIED / SUSPICIOUS`
4. Scores 0–100 against your profile → `STRONG / POSSIBLE / poor`
5. Alerts via **Telegram + Gmail** instantly for strong matches, daily digest for possibles
6. Dashboard: filter, save/dismiss/apply, deadline tracker, gap checklist

**Zero cost** — Gemini free tier + GitHub Actions (public repo) + Supabase free + Streamlit Community Cloud + Telegram + Gmail SMTP. No card anywhere.

---

## Quick start

1. Read [`docs/SETUP.md`](docs/SETUP.md) — non-technical setup guide
2. Read [`docs/HANDOVER.md`](docs/HANDOVER.md) — full architecture & deploy guide
3. Copy `.env.example` → `.env` and fill secrets (never commit `.env`)
4. Install & run locally:

```bash
pip install -r requirements.txt
# Run worker once
python -m worker.main --once
# Run dashboard
streamlit run app/streamlit_app.py
```

5. Deploy: push to public GitHub → enable Actions → add Secrets → deploy Streamlit → create cron-job.org job

---

## Folder structure

```
app/                  # Streamlit dashboard + login
worker/               # Background scout worker
  sources/            # Source adapters (RSS, scrape)
  extraction/         # AI extraction + cheap filters
  verification/       # Trust labels
  scoring/            # Matching & scoring
  alerts/             # Email + Telegram
  db/                 # Supabase client
  utils/              # dedup, hashing, rate-limit queue
config/
  sources.yaml        # All sources (add one = one entry)
  scoring_weights.yaml
supabase/
  schema.sql          # Full DB schema
.github/workflows/
  scout.yml           # Worker + heartbeat
  secret-scan.yml     # Blocks secret leaks
tests/                # pytest suite
docs/
  HANDOVER.md
  SETUP.md
```

---

## Free-tier limits (Nov 2026)

| Service | Limit | What happens | Mitigation |
|---|---|---|---|
| Gemini 2.5 Flash-Lite (free) | ~30 RPM, 1500 RPD, 250K TPM | 429 queue | Backoff + Supabase queue, merges extract+score in one call |
| Gemini 2.5 Flash (free) | ~10 RPM, 500 RPD | 429 | Use Flash-Lite for higher quota |
| GitHub Actions (public repo) | **Unlimited minutes**, cron best-effort ≥5m, disabled after 60d idle if no commit | Delayed/dropped runs | cron-job.org every 12m + backup cron :17/:47; heartbeat committed once a day (concurrency group prevents races) |
| Supabase Free | 500 MB DB, 1 GB storage, pauses after 7d idle | DB offline | Worker pings DB every run; healthchecks.io alerts if down |
| Streamlit Cloud | ~1 GB RAM, sleeps after 12h idle | Waking page | Ping via healthchecks/cron |
| Gmail SMTP | ~500 emails/day | Throttled | Dedup + digest |
| Telegram | 30 msg/sec | Throttled | Retry |
| healthchecks.io free | 20 checks, 45min grace | Alerts when pings stop | Worker pings at end of each run; alerts via Telegram+email if silent 45m |

See `docs/HANDOVER.md` for full table + fallback plan if any tier is withdrawn.

---

## Adding a source

1. Add entry to `config/sources.yaml` (see file for template)
2. If custom parsing needed: add `worker/sources/<name>.py` extending `BaseSource`
3. Test: `python -m worker.sources.test_source --source <name>`

---

## Security

- Repo is **public** — never commit profile, tokens, emails, results. All personal data lives in Supabase.
- Secrets via env vars / GitHub Secrets only.
- `secret-scan.yml` fails CI if a secret pattern is detected.
- Free-tier AI privacy: only public opportunity text + minimal profile summary (field/level/countries/funding) is sent to Gemini. No names, contacts, documents.

---

## License

MIT — use freely, but keep legitimacy checks intact. Do not use to spam applicants with fake opportunities.

