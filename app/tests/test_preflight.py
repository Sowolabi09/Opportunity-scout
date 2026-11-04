"""Preflight validation: bad secrets must fail fast with actionable messages."""
from worker.utils.preflight import check_env

GOOD_URL = "https://abcdefghijklmnopqrst.supabase.co"
GOOD_KEY = "eyJ" + "a" * 160
GOOD_GEM = "AIza" + "B" * 35


def base(**over):
    env = {
        "SUPABASE_URL": GOOD_URL,
        "SUPABASE_SERVICE_ROLE_KEY": GOOD_KEY,
        "GEMINI_API_KEY": GOOD_GEM,
        "GMAIL_USER": "me@gmail.com",
        "GMAIL_APP_PASSWORD": "abcdefghijklmnop",
        "ALERT_TO_EMAIL": "me@gmail.com",
    }
    env.update(over)
    return env


def test_good_config_passes():
    r = check_env(base())
    assert r["ok"], r["errors"]
    assert r["errors"] == []


def test_missing_supabase_url_is_fatal():
    r = check_env(base(SUPABASE_URL=""))
    assert not r["ok"]
    assert any("SUPABASE_URL" in e for e in r["errors"])


def test_rest_suffix_is_auto_corrected():
    r = check_env(base(SUPABASE_URL=GOOD_URL + "/rest/v1"))
    assert r["ok"], r["errors"]
    assert any("auto-corrected" in w for w in r["warnings"])


def test_dashboard_url_is_auto_corrected():
    r = check_env(base(SUPABASE_URL="https://supabase.com/dashboard/project/abcdefghijklmnopqrst"))
    assert r["ok"], r["errors"]
    assert any("abcdefghijklmnopqrst.supabase.co" in w for w in r["warnings"])


def test_trailing_slash_is_auto_corrected():
    r = check_env(base(SUPABASE_URL=GOOD_URL + "/"))
    assert r["ok"], r["errors"]


def test_publishable_key_rejected():
    r = check_env(base(SUPABASE_SERVICE_ROLE_KEY="sb_publishable_abc123"))
    assert not r["ok"]
    assert any("publishable" in e for e in r["errors"])


def test_new_sb_secret_key_accepted():
    r = check_env(base(SUPABASE_SERVICE_ROLE_KEY="sb_secret_abc123"))
    assert r["ok"], r["errors"]


def test_unknown_key_shape_only_warns():
    r = check_env(base(SUPABASE_SERVICE_ROLE_KEY="not-a-jwt"))
    assert r["ok"]
    assert any("key shape" in w for w in r["warnings"])


def test_odd_gemini_key_warns_but_continues():
    """The live API call is the authority on key validity, not a regex."""
    r = check_env(base(GEMINI_API_KEY="AIzaBROKEN123"))
    assert r["ok"]
    assert any("GEMINI_API_KEY" in w for w in r["warnings"])


def test_missing_gemini_only_warns():
    env = base()
    env.pop("GEMINI_API_KEY")
    r = check_env(env)
    assert r["ok"]
    assert any("GEMINI_API_KEY" in w for w in r["warnings"])


def test_short_app_password_rejected():
    r = check_env(base(GMAIL_APP_PASSWORD="mypassword"))
    assert not r["ok"]
    assert any("16 characters" in e for e in r["errors"])


def test_app_password_with_spaces_accepted():
    r = check_env(base(GMAIL_APP_PASSWORD="abcd efgh ijkl mnop"))
    assert r["ok"], r["errors"]


def test_new_aq_auth_key_accepted():
    """Google AI Studio now issues AQ.Ab... auth keys (mid-2026 format change)."""
    r = check_env(base(GEMINI_API_KEY="AQ.Ab8RN6Lkx9QpLm2vRt4YzS1bNc7Hd3Fg5Jk0Mw"))
    assert r["ok"], r["errors"]


def test_legacy_aiza_key_still_accepted():
    r = check_env(base(GEMINI_API_KEY="AIza" + "B" * 35))
    assert r["ok"], r["errors"]


def test_key_with_quotes_only_warns():
    r = check_env(base(GEMINI_API_KEY='"AQ.Ab8RN6Lkx9QpLm2vRt4YzS1bNc7Hd3Fg"'))
    assert r["ok"]


def test_retired_model_name_is_fatal():
    r = check_env(base(GEMINI_MODEL="gemini-1.5-flash"))
    assert not r["ok"]
    assert any("shut down" in e for e in r["errors"])


def test_restricted_25_model_only_warns():
    r = check_env(base(GEMINI_MODEL="gemini-2.5-flash-lite"))
    assert r["ok"]
    assert any("restricted" in w for w in r["warnings"])


def test_current_model_clean():
    r = check_env(base(GEMINI_MODEL="gemini-3.5-flash-lite"))
    assert r["ok"] and r["warnings"] == []


def test_normalize_supabase_url_variants():
    from worker.db.supabase_client import normalize_supabase_url as n
    assert n("https://abcd.supabase.co/") == "https://abcd.supabase.co"
    assert n("https://abcd.supabase.co/rest/v1") == "https://abcd.supabase.co"
    assert n("supabase.com/dashboard/project/abcdefghijklmnopqrst") == "https://abcdefghijklmnopqrst.supabase.co"
    assert n("abcdefghijklmnopqrst") == "https://abcdefghijklmnopqrst.supabase.co"
    assert n("abcd.supabase.co") == "https://abcd.supabase.co"
    assert n("") == ""
