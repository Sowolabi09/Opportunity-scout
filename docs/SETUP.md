# Opportunity Scout — Setup Guide (Plain English)

No coding needed. Follow steps 1–10 once, then just use the dashboard.

## What you get

- A private website (your dashboard) to edit your profile and see opportunities.
- An automatic worker that checks the internet every ~12 minutes and emails + Telegrams you immediately when a great match appears.
- Everything is free — no card at any step.

---

## Step 1 — Create accounts (all free, no card)

You need 4 accounts:

1. **Supabase** (database) — go to https://supabase.com → Sign up (GitHub login is easiest) → New project → pick region closest to you (EU or US) → set a strong DB password → wait 2 min.
2. **Google AI Studio** (AI) — https://aistudio.google.com → Sign in → Get API key → Create API key → copy it. This is `GEMINI_API_KEY`.
3. **GitHub** (worker host) — https://github.com → Sign up if needed.
4. **Telegram** — install Telegram app → create account if needed.

Optional but recommended:
- **cron-job.org** (reliable scheduler, free) — https://cron-job.org → Sign up.
- **Streamlit** (dashboard host, free) — https://share.streamlit.io → Sign in with GitHub.

All ask no card.

---

## Step 2 — Prepare the database

1. In Supabase → your project → left menu **SQL Editor** → New query.
2. Open the file `supabase/schema.sql` from this repo (in GitHub, click it → Raw → copy all).
3. Paste into Supabase SQL editor → Run. Should say success.
4. Go to **Project Settings** (gear icon) → **API** → copy:
   - `Project URL` → this is `SUPABASE_URL`
   - `service_role` key (secret, keep safe) → `SUPABASE_SERVICE_ROLE_KEY` — this is the ONLY key needed (RLS has no anon policies; service_role bypasses RLS). The dashboard runs server-side on Streamlit, so the key never leaves the server and is gated by `DASHBOARD_PASSWORD`.

---

## Step 3 — Put the code on GitHub

1. Create a new repo on GitHub → name `opportunity-scout` → make it **Public** (public repos get free Actions minutes) → do NOT add README (we already have one).
2. On your computer (or in GitHub web upload):
   - Download this repo as ZIP → unzip.
   - Push to your new repo (or use GitHub Desktop / `git push`).
3. In your GitHub repo → Settings → Secrets and variables → Actions → New repository secret → add each of these (copy/paste exactly):

| Secret name | Where to find it |
|---|---|
| `GEMINI_API_KEY` | from Step 1 |
| `GEMINI_MODEL` | `gemini-2.5-flash-lite` (current free tier; 2.0 models shut down June 2026) — see `config/ai_limits.yaml` |
| `SUPABASE_URL` | from Step 2 |
| `SUPABASE_SERVICE_ROLE_KEY` | from Step 2 (only key needed) |
| `TELEGRAM_BOT_TOKEN` | see Step 4 |
| `TELEGRAM_CHAT_ID` | see Step 4 |
| `GMAIL_USER` | your Gmail address |
| `GMAIL_APP_PASSWORD` | see Step 5 |
| `ALERT_TO_EMAIL` | your email (where alerts go) |
| `DASHBOARD_PASSWORD` | choose a strong password for the dashboard |

4. Also create a **fine-grained PAT** for the scheduler:
   - GitHub → Settings → Developer settings → Personal access tokens → Fine-grained → Generate → select ONLY your `opportunity-scout` repo → permissions: Actions: Read & Write, Contents: Read & Write, Metadata: Read → Generate → copy as `GH_PAT` secret.

---

## Step 4 — Telegram bot (2 min)

1. In Telegram, search `@BotFather` → Start → send `/newbot` → follow prompts (pick name like `oppscout_bot`) → it gives you a `BOT_TOKEN` like `123456:ABC...` → save as `TELEGRAM_BOT_TOKEN`.
2. Search your new bot → Start → send any message like `hi`.
3. In your browser, open `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` (replace `<YOUR_TOKEN>`) → find `"chat":{"id": 123456789` → that number is `TELEGRAM_CHAT_ID` → save it.

Test: we will verify Telegram works in Step 8.

---

## Step 5 — Gmail alerts

1. Gmail → https://myaccount.google.com → Security → **2-Step Verification** → turn ON (required).
2. Then Security → **App passwords** (search it) → create → name `Opportunity Scout` → it shows `abcd efgh ijkl mnop` → copy → save as `GMAIL_APP_PASSWORD`. `GMAIL_USER` is your full Gmail address.

If you don't want Gmail, you can skip — Telegram alone still works.

---

## Step 6 — Deploy the dashboard (Streamlit)

1. Go to https://share.streamlit.io → New app → pick your `opportunity-scout` repo → Branch `main` → Main file `app/streamlit_app.py` → Advanced → paste secrets in TOML (copy from `.env.example` but use TOML format `KEY = "value"`).
2. Deploy → wait 2 min → you get `https://your-name-opportunity-scout.streamlit.app` → open it → log in with `DASHBOARD_PASSWORD`.

If it sleeps after 12h idle, that's normal. Next visitor sees "Waking up" for ~30s. Free workaround: create an UptimeRobot (free) monitor that pings the URL every 10 min, or reuse your cron-job.org job.

---

## Step 7 — Reliable scheduling (cron-job.org)

GitHub's own cron is best-effort (can be delayed/dropped). We add a free external nudge:

1. cron-job.org → Add job → Title `Opportunity Scout trigger` → URL `https://api.github.com/repos/YOUR_USERNAME/opportunity-scout/actions/workflows/scout.yml/dispatches`
   - Replace `YOUR_USERNAME`.
2. Method `POST`
3. Headers: `Authorization: Bearer YOUR_GH_PAT` (replace with your PAT) + `Accept: application/vnd.github+json` + `Content-Type: application/json`
4. Body: `{"ref":"main"}`
5. Schedule: Every 12 minutes → Create.
6. Check Execution log shows `200` after 12 min. GitHub Actions tab should show new runs.

Backup: the repo already has GitHub cron at :17 and :47 — so even if cron-job.org is down, it still runs hourly.

---

## Step 8 — Test: one real email + one real Telegram

1. In GitHub → your repo → Actions → Scout Worker → Run workflow → Run → wait 2–3 min → should be green. Check logs for `new_opportunities`.
2. To force a test alert without waiting for a real strong match:
   - Option A: lower threshold in dashboard → Profile → set Strong threshold to `0` → next run will alert on anything.
   - Option B: locally run `python -m worker.alerts.emailer` (if you set up local env).
3. You should get:
   - Telegram: short card with title, deadline, trust, score + link.
   - Email: full opportunity card (funding, eligibility, docs, costs, gaps).
4. If not received: check spam, check Actions logs for `[email] failed` or `[telegram] failed`, verify secrets, verify chat_id by sending another message to your bot.

**Do this before calling it done.**

---

## Step 9 — Fill your profile

1. Open dashboard → Log in → Profile / Settings.
2. Fill all fields:
   - Academic: course, year, CGPA, research, lab skills
   - Goals: target level (MSc/PhD), preferred countries, start date
   - Fields: primary = Physiology, other = whatever you'd consider
   - Money: funding need + upfront budget
   - Readiness: IELTS/TOEFL, referees, documents you have
   - Alerts: threshold, digest time, quiet hours
3. Optional: paste your CV text → it auto-fills where possible (stored in Supabase, not sent to AI).
4. Save. Worker uses new settings immediately on next run (within 12 min).

---

## Step 10 — Daily use

- **Dashboard → Dashboard tab**: All opportunities. Filters: field, country, level, funding, deadline. Tabs: Primary vs Other fields (so other fields never crowd your main results).
- **Actions**: Save / Dismiss / Mark-as-applied. Dismissed are hidden by default (toggle to show).
- **Deadline tracker**: 60/30/7 day buckets + chart vs match score.
- **Per-opportunity gaps**: e.g. "Needs IELTS 6.5 — you haven't taken it" so you know what to prepare.
- **Trust label**: VERIFIED (on official domain) / UNVERIFIED (confirm on official site) / SUSPICIOUS (logged only, not alerted).
- **Cost breakdown**: each figure marked OFFICIAL (with source) or ESTIMATED — verify estimates on official link.

---

## If something stops working

| Symptom | Check |
|---|---|
| No new opportunities for hours | GitHub → Actions → last run green? → Check `heartbeat.json` last_run. If red, read logs. |
| Dashboard shows "Waking up" | Normal free-tier sleep — wait 30s. Add UptimeRobot ping if annoying. |
| Dashboard empty forever | Check Supabase → Table Editor → opportunities → any rows? If not, worker not writing → check SUPABASE_URL/keys in GitHub Secrets. |
| No emails | Check spam. In Actions logs search `[email]`. Verify GMAIL_APP_PASSWORD still valid (Google expires after long idle). |
| No Telegram | Send your bot a message → retry `getUpdates` → verify CHAT_ID. Check logs for `[telegram] 429`. |
| Worker fails with 429 | Gemini quota hit — check `https://aistudio.google.com/rate-limit` for your live RPM/RPD. Worker queues to Supabase `ai_queue` and retries next run (survives runner wipe). Stay under `config/ai_limits.yaml` (Flash-Lite 28/1400) or switch model. |
| Supabase "paused" | Free projects pause after 7 days no API. Go to Supabase dashboard → Resume → worker will keep it warm going forward. You get an email alert if this happens (if alerts still work). |
| GitHub cron stopped after 60 days | That's the 60-day idle disable. Heartbeat now commits once a day (concurrency group prevents races) — but if it happens, make any commit or enable workflows. |
| No healthchecks ping 45m | Check `HEALTHCHECKS_PING_URL` secret; worker pings at end of each run. Healthchecks.io will email/Telegram you when pings stop >45m. Also set `GH_PAT_EXPIRY` to get 7-day token expiry warning. |
| Secret leaked in repo | Revoke it immediately in provider dashboard → generate new → update GitHub + Streamlit Secrets. Secret-scan workflow would have blocked push if it detected a real key. |

---

## Privacy notes

- Your profile + opportunities + chat IDs live ONLY in Supabase (and GitHub Secrets). Repo is public but contains none of it.
- Free Gemini may use prompts to improve products per Google terms. We send only public opportunity text + minimal summary (field/level/countries/funding). No names/contacts/documents.
- Never store passport numbers or bank details in the profile — the form doesn't even have those fields.

---

## Need help?

- Read `docs/HANDOVER.md` for engineer-level details + free-tier fallbacks if any service is withdrawn.
- In GitHub → Issues → open one (don't include secrets).
- To rotate a key: generate new in provider → update GitHub Secrets + Streamlit Secrets → test run.

Good luck — your scout is on duty 24/7. 🎓
