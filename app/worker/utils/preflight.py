"""
Preflight environment validation.

Fails fast (seconds, not minutes) when a secret is malformed, instead of
burning the whole GitHub Actions timeout on doomed network calls.

Used by worker/main.py at startup. Returns structured errors so the log is
actionable: every message says exactly which secret is wrong and what the
correct shape looks like.
"""
import os
import re

from worker.db.supabase_client import normalize_supabase_url

# https://<project-ref>.supabase.co  (trailing slash tolerated, no path)
_SUPABASE_URL_RE = re.compile(r"^https://[a-z0-9-]+\.supabase\.co/?$", re.I)
# Gemini keys come in two valid shapes:
#   legacy standard keys:  AIza + 35 chars   (retiring Sept 2026)
#   new auth keys (2026+): AQ.Ab... + ~30-510 chars  <-- what AI Studio issues now
_GEMINI_KEY_RE = re.compile(r"^(?:AIza[0-9A-Za-z_\-]{20,}|AQ\.[A-Za-z0-9._\-]{20,})$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _clean(value):
    return (value or "").strip()


def check_env(env=None):
    """Validate required secrets.

    Returns dict:
      {"errors": [...], "warnings": [...], "ok": bool}
    `errors` are fatal (exit non-zero), `warnings` are optional features.
    """
    env = os.environ if env is None else env
    errors, warnings = [], []

    # ---- Supabase (required) ----
    # The URL is auto-repaired from the shapes people commonly paste, so a
    # malformed value here really means "absent or unrecoverable".
    raw_url = _clean(env.get("SUPABASE_URL"))
    url = normalize_supabase_url(raw_url)
    if not url:
        errors.append(
            "SUPABASE_URL is empty. Expected: https://<project-ref>.supabase.co "
            "(Supabase -> Settings -> Data API -> Project URL)"
        )
    elif not _SUPABASE_URL_RE.match(url):
        errors.append(
            "SUPABASE_URL could not be interpreted. Expected exactly "
            "https://<project-ref>.supabase.co — e.g. https://abcdefghijklmnop.supabase.co "
            "(no dashboard path, no /rest/v1, no spaces)."
        )
    elif url != raw_url.rstrip("/").replace("http://", "https://", 1):
        warnings.append(f"SUPABASE_URL was auto-corrected to {url}")

    key = _clean(env.get("SUPABASE_SERVICE_ROLE_KEY"))
    if not key:
        errors.append(
            "SUPABASE_SERVICE_ROLE_KEY is not set. Use the service_role/secret key "
            "(long string starting with 'eyJ'), not the anon/publishable key."
        )
    elif key.startswith("sb_publishable"):
        errors.append(
            "SUPABASE_SERVICE_ROLE_KEY is a publishable (anon) key. RLS has no anon "
            "policies, so nothing can be written. Use the server key instead: either "
            "'sb_secret_...' (new) or the legacy 'eyJ...' service_role JWT."
        )
    elif key.startswith("sb_secret"):
        pass  # new server-side secret key — valid
    elif not key.startswith("eyJ"):
        warnings.append(
            "SUPABASE_SERVICE_ROLE_KEY does not look like a known key shape "
            "(expected 'eyJ...' legacy JWT or 'sb_secret_...'). Continuing — the "
            "live Supabase connection check will give the definitive answer."
        )

    # ---- Gemini (optional; without it we do plain-code scoring only) ----
    gem = _clean(env.get("GEMINI_API_KEY"))
    if not gem:
        warnings.append(
            "GEMINI_API_KEY not set — running keyword scoring only (no AI extraction)."
        )
    elif not _GEMINI_KEY_RE.match(gem):
        warnings.append(
            "GEMINI_API_KEY doesn't match a known shape ('AIza...' or 'AQ.Ab...'). "
            "Continuing — the live Gemini check below will confirm whether it works."
        )

    # ---- Model name sanity (informational) ----
    model = _clean(env.get("GEMINI_MODEL"))
    if model:
        if model.startswith(("gemini-1.", "gemini-2.0")):
            errors.append(
                f"GEMINI_MODEL='{model}' has been shut down by Google. Use "
                "'gemini-3.5-flash-lite' (free tier, recommended) or 'gemini-3.8-flash'."
            )
        elif model.startswith("gemini-2.5"):
            warnings.append(
                f"GEMINI_MODEL='{model}' is restricted to projects that already used it; "
                "new projects get 404s. Prefer 'gemini-3.5-flash-lite'."
            )

    # ---- Email alerts (optional but recommended) ----
    user = _clean(env.get("GMAIL_USER"))
    if user and not _EMAIL_RE.match(user):
        errors.append(f"GMAIL_USER is not a valid email address: {user!r}")
    pw = _clean(env.get("GMAIL_APP_PASSWORD")).replace(" ", "")
    if user and not pw:
        warnings.append("GMAIL_APP_PASSWORD not set — email alerts disabled.")
    elif pw and len(pw) != 16:
        errors.append(
            f"GMAIL_APP_PASSWORD should be 16 characters (got {len(pw)}). Use a Google "
            "App Password from https://myaccount.google.com/apppasswords, not your normal "
            "Gmail password."
        )
    to = _clean(env.get("ALERT_TO_EMAIL"))
    if to and not _EMAIL_RE.match(to):
        errors.append(f"ALERT_TO_EMAIL is not a valid email address: {to!r}")

    return {"errors": errors, "warnings": warnings, "ok": not errors}


def print_report(result):
    for w in result["warnings"]:
        print(f"[preflight][warn] {w}")
    for e in result["errors"]:
        print(f"[preflight][ERROR] {e}")
    if result["ok"]:
        print("[preflight] config OK")
    return result["ok"]
