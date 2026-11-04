"""Dashboard smoke test — every page must render without exceptions.

Runs the real Streamlit script through AppTest using the built-in demo data
(no Supabase credentials), logs in, and walks the sidebar pages. This is what
catches things like the naive-vs-tz-aware deadline comparison, which rendered
fine on the main tab but crashed the Deadline tracker.
"""
import os
import warnings

import pytest

streamlit = pytest.importorskip("streamlit")

os.environ.setdefault("DASHBOARD_PASSWORD", "test123")


def _app():
    from streamlit.testing.v1 import AppTest
    os.environ["DASHBOARD_PASSWORD"] = "test123"
    for k in ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"):
        os.environ.pop(k, None)  # force demo-data branch
    at = AppTest.from_file("app/streamlit_app.py", default_timeout=90)
    at.run()
    return at


def _login(at):
    at.text_input[1].set_value("test123")
    at.button[0].click()
    at.run()
    return at


def test_login_required():
    at = _app()
    assert [t.value for t in at.title] == ["🔐 Opportunity Scout — Login"]


def test_dashboard_renders_after_login():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        at = _login(_app())
    assert at.exception == [], [e.value for e in at.exception]
    labels = [t.label for t in at.tabs]
    assert any("Deadline tracker" in l for l in labels)


def test_deadline_tracker_no_tz_crash():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        at = _login(_app())
    # dataframes only appear if the tz-aware comparison worked
    assert len(at.dataframe) >= 1
    assert at.exception == []


def test_all_pages_render():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        at = _login(_app())
    for page in ["Profile / Settings", "Sources & Health", "Help", "Dashboard"]:
        at.radio[0].set_value(page)
        at.run()
        assert at.exception == [], f"{page}: {[e.value for e in at.exception]}"
