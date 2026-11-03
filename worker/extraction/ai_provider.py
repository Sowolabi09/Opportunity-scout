"""Provider-agnostic AI interface.

Gemini is called through the REST API (generativelanguage.googleapis.com)
instead of the deprecated `google-generativeai` SDK, because:

  * Google AI Studio now issues "Auth keys" starting with `AQ.Ab...`
    (mid-2026 format change). The native REST endpoint accepts them via the
    `x-goog-api-key` header; some SDKs/OpenAI-compatible shims do not.
  * The 2.5 family is restricted to accounts that already used it, and new
    projects get 404s. Model availability therefore has to be discovered at
    runtime, not hard-coded.
  * Fewer dependencies => faster CI installs and no resolver conflicts.

Behaviour:
  * On startup the provider lists models available to the key and picks the
    configured one, or the first entry of a preference list that exists.
  * An invalid key raises FatalAIError, which the worker turns into an
    immediate exit instead of hammering the API for 15 minutes.
"""
import os
import time
import json
import yaml

import requests

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"

# Preference order — cheapest/free high-volume models first. Google's own
# recommendation for new projects (Nov 2026) is 3.5 Flash-Lite or 3.8 Flash.
DEFAULT_MODEL = "gemini-3.5-flash-lite"
PREFERRED_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.8-flash",
    "gemini-3.6-flash",
    "gemini-3-flash-preview",
    "gemini-2.5-flash-lite",  # legacy access only
]
# Models that are restricted to pre-existing projects / shut down. Calling
# them on a fresh project returns 404 "no longer available to new users".
RETIRED_MODELS = {
    "gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-1.5-flash", "gemini-1.5-pro",
}


class FatalAIError(RuntimeError):
    """Unrecoverable: wrong key, no usable model, permissions. Stop the run."""


def load_ai_config():
    cfg_path = os.getenv("AI_LIMITS_CONFIG", "config/ai_limits.yaml")
    try:
        with open(cfg_path) as f:
            return (yaml.safe_load(f) or {}).get("gemini", {}) or {}
    except Exception:
        return {}


def load_ai_model():
    cfg = load_ai_config()
    return os.getenv("GEMINI_MODEL") or cfg.get("model") or DEFAULT_MODEL


class AIProvider(object):
    def extract_opportunity(self, url: str, html_text: str, source_name: str) -> dict:
        raise NotImplementedError

    def score_opportunity(self, opportunity: dict, profile_summary: dict) -> dict:
        raise NotImplementedError

    def extract_and_score(self, url, html_text, source_name, profile_summary):
        extraction = self.extract_opportunity(url, html_text, source_name)
        if not extraction.get("is_opportunity"):
            return extraction, {}
        scoring = self.score_opportunity(extraction, profile_summary)
        return extraction, scoring


def _strip_json(raw: str) -> str:
    cleaned = (raw or "").strip()
    if "```" in cleaned:
        parts = cleaned.split("```")
        cleaned = parts[1] if len(parts) > 1 else cleaned
        if cleaned.lstrip().startswith("json"):
            cleaned = cleaned.lstrip()[4:]
    return cleaned.strip()


class GeminiProvider(AIProvider):
    def __init__(self, model: str = None, api_key: str = None, session=None):
        self.api_key = (api_key or os.getenv("GEMINI_API_KEY") or "").strip()
        self.requested_model = model or load_ai_model()
        self.model_name = None          # resolved lazily
        self._available = None
        self._session = session or requests.Session()
        self.checked = False

    # ---------------- plumbing ----------------
    def _headers(self):
        return {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}

    def _get(self, path, **kw):
        return self._session.get(f"{GEMINI_BASE}{path}", headers=self._headers(), timeout=30, **kw)

    def _post(self, path, payload, timeout=90):
        return self._session.post(f"{GEMINI_BASE}{path}", headers=self._headers(),
                                  json=payload, timeout=timeout)

    @staticmethod
    def _error_text(resp):
        try:
            err = resp.json().get("error", {})
            return f"{err.get('code', resp.status_code)} {err.get('status', '')}: {err.get('message', '')}".strip()
        except Exception:
            return f"{resp.status_code}: {resp.text[:300]}"

    def list_models(self):
        """Names of models this key can call for generateContent."""
        if self._available is not None:
            return self._available
        models = []
        try:
            resp = self._get("/models", params={"pageSize": 200})
            if resp.status_code in (400, 401, 403):
                raise FatalAIError(
                    f"Gemini rejected the API key — {self._error_text(resp)}. "
                    "Re-copy the key from https://aistudio.google.com/apikey "
                    "(it should start with 'AQ.' or 'AIza') and update the "
                    "GEMINI_API_KEY secret."
                )
            data = resp.json() if resp.status_code == 200 else {}
            for m in data.get("models", []):
                if "generateContent" in (m.get("supportedGenerationMethods") or []):
                    models.append((m.get("name") or "").split("/")[-1])
        except FatalAIError:
            raise
        except Exception as e:
            print(f"[Gemini] could not list models ({e}); trying configured model directly")
        self._available = models
        return models

    def resolve_model(self):
        """Pick a model that exists for this key. Runs once."""
        if self.model_name:
            return self.model_name
        available = self.list_models()
        wanted = (self.requested_model or DEFAULT_MODEL).strip()

        if available:
            if wanted in available:
                self.model_name = wanted
            else:
                for cand in PREFERRED_MODELS:
                    if cand in available:
                        self.model_name = cand
                        print(f"[Gemini] configured model '{wanted}' is not available to this key; "
                              f"using '{cand}' instead")
                        break
                else:
                    self.model_name = wanted
                    print(f"[Gemini] WARNING '{wanted}' not in available models: "
                          f"{', '.join(sorted(available)[:12])}...")
        else:
            self.model_name = wanted

        if wanted in RETIRED_MODELS:
            raise FatalAIError(
                f"Model '{wanted}' has been shut down by Google. Use a current model "
                f"(e.g. {DEFAULT_MODEL}). Set the GEMINI_MODEL secret accordingly."
            )
        return self.model_name

    def _call(self, prompt: str, retries=3):
        if not self.api_key:
            raise FatalAIError(
                "GEMINI_API_KEY is not set. Add it in Settings -> Secrets -> Actions."
            )
        model = self.resolve_model()
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 2048},
        }
        last = ""
        for attempt in range(retries):
            try:
                resp = self._post(f"/models/{model}:generateContent", payload)
            except Exception as e:
                last = str(e)
                print(f"[Gemini] network error ({e}); retry {attempt+1}/{retries}")
                time.sleep(2 ** attempt)
                continue

            if resp.status_code == 200:
                data = resp.json()
                try:
                    cands = data.get("candidates") or []
                    parts = (cands[0].get("content") or {}).get("parts") or []
                    text = "".join(p.get("text", "") for p in parts)
                    if text:
                        return text
                    reason = (cands[0].get("finishReason") if cands else "no candidates")
                    print(f"[Gemini] empty response (finishReason={reason})")
                    return ""
                except Exception as e:
                    print(f"[Gemini] could not parse response: {e}")
                    return ""

            msg = self._error_text(resp)

            if resp.status_code == 429:
                wait = (2 ** attempt) * 3
                print(f"[Gemini] 429 rate limit — backing off {wait}s (attempt {attempt+1}/{retries}, model={model})")
                time.sleep(wait)
                last = msg
                continue

            if resp.status_code in (401, 403) or "API_KEY_INVALID" in msg or "API key not valid" in msg:
                raise FatalAIError(
                    f"Gemini rejected the API key — {msg}. Re-copy it from "
                    "https://aistudio.google.com/apikey and update the GEMINI_API_KEY secret."
                )

            if resp.status_code == 404:
                # model not found / not available to this project
                self.model_name = None
                self._available = None
                if attempt == 0:
                    print("[Gemini] 404 on model — re-detecting available models")
                    continue
                raise FatalAIError(
                    f"Model '{model}' is not available to this key — {msg}. "
                    "Set GEMINI_MODEL to a current model (e.g. "
                    f"{DEFAULT_MODEL})."
                )

            if 500 <= resp.status_code < 600:
                wait = (2 ** attempt) * 2
                print(f"[Gemini] {resp.status_code} server error — retry in {wait}s")
                time.sleep(wait)
                last = msg
                continue

            raise FatalAIError(f"Gemini request failed — {msg}")

        raise FatalAIError(f"Gemini unavailable after {retries} attempts — {last}")

    # ---------------- tasks ----------------
    def extract_opportunity(self, url, html_text, source_name):
        snippet = (html_text or "")[:12000]
        prompt = f"""You are Opportunity Scout extractor. Given this webpage text from "{source_name}" ({url}), extract a scholarship/fellowship/MSc/PhD/internship opportunity if present.
Return ONLY valid JSON with these keys (use null if unknown):
{{
  "is_opportunity": true/false,
  "title": "...",
  "funder": "...",
  "host": "...",
  "country": "...",
  "level": "MSc|PhD|fellowship|internship|exchange|other",
  "field": "physiology|neuroscience|biomedical|other",
  "funding_type": "full|partial|none|unknown",
  "funding_covers": {{"tuition": true, "stipend": "amount if mentioned", "flights": true/false, "visa": true/false, "health_insurance": true/false}},
  "eligibility": "who can apply, include if Nigerians eligible",
  "nigeria_eligibility": "eligible|excluded|unclear (only 'excluded' if explicitly excludes Nigeria/Nigerians; 'unclear' if not mentioned)",
  "min_grade": "...",
  "opening_date": "YYYY-MM-DD or null",
  "deadline": "YYYY-MM-DD or null (null if rolling/unknown)",
  "deadline_status": "dated|rolling|unknown",
  "deadline_tz": "timezone if mentioned",
  "intake_year": 2027 or null (academic intake year),
  "required_docs": ["CV","transcript",...],
  "application_steps": "plain language steps",
  "cost_breakdown": {{"application_fee": {{"amount": "...", "source": "OFFICIAL|ESTIMATED"}}, "language_test": {{"amount": "...", "source": "..."}}}},
  "official_link": "best official URL",
  "confidence": 0.0-1.0
}}
Rules:
- If page is not an opportunity listing, set is_opportunity false.
- Be conservative: if funding not clearly stated, use "unknown".
- Never invent deadlines or fees. If deadline says "rolling" or "open until filled", set deadline null and deadline_status rolling.
- For Nigeria: only 'excluded' if text explicitly says Nigeria not eligible; otherwise 'eligible' if Nigeria listed, 'unclear' if not mentioned.
WEBPAGE TEXT:
{snippet}
"""
        raw = self._call(prompt)
        try:
            return json.loads(_strip_json(raw))
        except Exception as e:
            print(f"[Gemini extract] JSON parse failed: {e} | raw[:300]={raw[:300]}")
            return {"is_opportunity": False, "raw": raw[:2000]}

    def extract_and_score(self, url, html_text, source_name, profile_summary):
        """Merged extraction + scoring in one call to save quota."""
        snippet = (html_text or "")[:12000]
        prompt = f"""You are Opportunity Scout. Do extraction AND scoring in one call.
Source: "{source_name}" ({url})
Profile (minimal): {json.dumps(profile_summary)}
WEBPAGE TEXT:
{snippet}
First extract opportunity as JSON, then score 0-100.

Return ONLY valid JSON with:
{{
  "is_opportunity": true/false,
  "title": "...", "funder": "...", "host": "...", "country": "...", "level": "...", "field": "...",
  "funding_type": "full|partial|none|unknown", "funding_covers": {{}},
  "eligibility": "...", "nigeria_eligibility": "eligible|excluded|unclear",
  "deadline": "YYYY-MM-DD or null", "deadline_status": "dated|rolling|unknown", "intake_year": 2027,
  "required_docs": [], "application_steps": "...", "cost_breakdown": {{}}, "official_link": "...",
  "score": 78, "reasons": "why it matched", "gaps": ["Needs IELTS 6.5..."]
}}
Rules: same as extractor + scoring weights field_fit 0.3 country 0.15 funding 0.2 readiness 0.15 level 0.1 deadline 0.1
Only score if is_opportunity true.
"""
        raw = self._call(prompt)
        try:
            j = json.loads(_strip_json(raw))
            if not j.get("is_opportunity"):
                return j, {}
            scoring = {"score": j.pop("score", 0), "reasons": j.pop("reasons", ""), "gaps": j.pop("gaps", [])}
            return j, scoring
        except Exception as e:
            print(f"[Gemini merge] parse fail: {e}; falling back to extract only")
            return self.extract_opportunity(url, html_text, source_name), {}

    def score_opportunity(self, opportunity, profile_summary):
        prompt = f"""You are Opportunity Scout scorer. Score this opportunity 0-100 for the student profile.
PROFILE SUMMARY (minimal, no PII): {json.dumps(profile_summary)}
OPPORTUNITY: {json.dumps(opportunity)}
Weights: field_fit 0.3, country 0.15, funding 0.2, readiness 0.15, level 0.1, deadline 0.1
Hard filters: reject if explicitly excludes Nigerians, funding mismatch.
Return ONLY JSON:
{{"score": 78, "reasons": "Strong physiology PhD match...", "gaps": ["Needs IELTS 6.5 — you have not taken IELTS"]}}
"""
        raw = self._call(prompt)
        try:
            return json.loads(_strip_json(raw))
        except Exception as e:
            print(f"[Gemini score] parse fail: {e}")
            return {"score": 0, "reasons": "Scoring failed", "gaps": []}


def get_provider(name: str = None) -> AIProvider:
    name = (name or os.getenv("AI_PROVIDER", "gemini")).lower()
    if name == "gemini":
        return GeminiProvider()
    raise ValueError(f"Unknown AI_PROVIDER {name}")
