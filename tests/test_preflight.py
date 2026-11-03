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


def test_rest_suffix_rejected_with_hint():
    r = check_env(base(SUPABASE_URL=GOOD_URL + "/rest/v1"))
    assert not r["ok"]
    assert any("/rest/v1" in e for e in r["errors"])


def test_anon_key_rejected():
    r = check_env(base(SUPABASE_SERVICE_ROLE_KEY="not-a-jwt"))
    assert not r["ok"]
    assert any("eyJ" in e for e in r["errors"])


def test_broken_gemini_key_rejected():
    r = check_env(base(GEMINI_API_KEY="AIzaBROKEN123"))
    assert not r["ok"]
    assert any("GEMINI_API_KEY" in e for e in r["errors"])


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


def test_key_with_quotes_rejected():
    r = check_env(base(GEMINI_API_KEY='"AQ.Ab8RN6Lkx9QpLm2vRt4YzS1bNc7Hd3Fg"'))
    assert not r["ok"]


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
