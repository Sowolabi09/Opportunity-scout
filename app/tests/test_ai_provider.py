"""Gemini REST provider: AQ. keys, model auto-detection, fast-fail on bad keys."""
import json

import pytest
import responses

from worker.extraction.ai_provider import (
    GeminiProvider,
    FatalAIError,
    DEFAULT_MODEL,
)

BASE = "https://generativelanguage.googleapis.com/v1beta"


def _models_payload(*names):
    return {
        "models": [
            {"name": f"models/{n}", "supportedGenerationMethods": ["generateContent", "countTokens"]}
            for n in names
        ]
    }


def _ok_text(text):
    return {"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}]}


@responses.activate
def test_picks_preferred_model_when_configured_one_is_gone():
    """Configured 2.5 model missing (new-project restriction) -> auto fallback."""
    responses.add(responses.GET, f"{BASE}/models", json=_models_payload("gemini-3.5-flash-lite", "gemini-3.8-flash"), status=200)
    responses.add(responses.POST, f"{BASE}/models/gemini-3.5-flash-lite:generateContent", json=_ok_text("OK"), status=200)

    p = GeminiProvider(model="gemini-2.5-flash-lite", api_key="AQ.Ab8RN6fake")
    assert p.resolve_model() == "gemini-3.5-flash-lite"
    assert p._call("hi") == "OK"


@responses.activate
def test_configured_model_used_when_available():
    responses.add(responses.GET, f"{BASE}/models", json=_models_payload("gemini-3.8-flash", "gemini-3.5-flash-lite"), status=200)
    responses.add(responses.POST, f"{BASE}/models/gemini-3.8-flash:generateContent", json=_ok_text("OK"), status=200)

    p = GeminiProvider(model="gemini-3.8-flash", api_key="AQ.Ab8RN6fake")
    assert p.resolve_model() == "gemini-3.8-flash"


@responses.activate
def test_invalid_key_raises_fatal_immediately():
    responses.add(
        responses.GET, f"{BASE}/models",
        json={"error": {"code": 400, "status": "INVALID_ARGUMENT", "message": "API key not valid. Please pass a valid API key."}},
        status=400,
    )
    p = GeminiProvider(model="gemini-3.5-flash-lite", api_key="AQ.wrong")
    with pytest.raises(FatalAIError) as ei:
        p.resolve_model()
    assert "GEMINI_API_KEY" in str(ei.value)


@responses.activate
def test_401_on_generate_is_fatal():
    responses.add(responses.GET, f"{BASE}/models", json=_models_payload("gemini-3.5-flash-lite"), status=200)
    responses.add(
        responses.POST, f"{BASE}/models/gemini-3.5-flash-lite:generateContent",
        json={"error": {"code": 403, "status": "PERMISSION_DENIED", "message": "API key not valid"}},
        status=403,
    )
    p = GeminiProvider(model="gemini-3.5-flash-lite", api_key="bad")
    with pytest.raises(FatalAIError):
        p._call("hi")


@responses.activate
def test_429_retries_then_succeeds(monkeypatch):
    import worker.extraction.ai_provider as ap
    monkeypatch.setattr(ap.time, "sleep", lambda *_: None)
    responses.add(responses.GET, f"{BASE}/models", json=_models_payload("gemini-3.5-flash-lite"), status=200)
    responses.add(responses.POST, f"{BASE}/models/gemini-3.5-flash-lite:generateContent", status=429, json={"error": {"message": "quota"}})
    responses.add(responses.POST, f"{BASE}/models/gemini-3.5-flash-lite:generateContent", json=_ok_text("OK"), status=200)

    p = GeminiProvider(model="gemini-3.5-flash-lite", api_key="AQ.fake")
    assert p._call("hi") == "OK"


@responses.activate
def test_retired_model_refused():
    responses.add(responses.GET, f"{BASE}/models", json=_models_payload("gemini-2.0-flash"), status=200)
    p = GeminiProvider(model="gemini-2.0-flash", api_key="AQ.fake")
    with pytest.raises(FatalAIError):
        p.resolve_model()


@responses.activate
def test_json_extraction_parses_fenced_output():
    responses.add(responses.GET, f"{BASE}/models", json=_models_payload("gemini-3.5-flash-lite"), status=200)
    body = {"is_opportunity": True, "title": "MSc Physiology", "field": "physiology"}
    responses.add(
        responses.POST, f"{BASE}/models/gemini-3.5-flash-lite:generateContent",
        json=_ok_text("```json\n" + json.dumps(body) + "\n```"), status=200,
    )
    p = GeminiProvider(model="gemini-3.5-flash-lite", api_key="AQ.fake")
    out = p.extract_opportunity("https://x.test", "text", "src")
    assert out["title"] == "MSc Physiology"


def test_default_model_is_not_retired():
    assert not DEFAULT_MODEL.startswith(("gemini-1.", "gemini-2.0"))
