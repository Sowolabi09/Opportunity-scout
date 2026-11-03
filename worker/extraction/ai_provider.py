"""Provider-agnostic AI interface."""
import os, time, json, yaml
from abc import ABC, abstractmethod

def load_ai_model():
    cfg_path = os.getenv("AI_LIMITS_CONFIG", "config/ai_limits.yaml")
    try:
        with open(cfg_path) as f:
            cfg = yaml.safe_load(f)
            return cfg.get("gemini", {}).get("model", "gemini-2.5-flash-lite")
    except:
        return os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")

class AIProvider(ABC):
    @abstractmethod
    def extract_opportunity(self, url: str, html_text: str, source_name: str) -> dict:
        pass
    @abstractmethod
    def score_opportunity(self, opportunity: dict, profile_summary: dict) -> dict:
        pass
    def extract_and_score(self, url: str, html_text: str, source_name: str, profile_summary: dict) -> tuple[dict, dict]:
        """Optional merged call: returns (extraction, scoring). Default does two calls."""
        extraction = self.extract_opportunity(url, html_text, source_name)
        if not extraction.get("is_opportunity"):
            return extraction, {}
        scoring = self.score_opportunity(extraction, profile_summary)
        return extraction, scoring

class GeminiProvider(AIProvider):
    def __init__(self, model: str = None, api_key: str = None):
        self.model_name = model or load_ai_model()
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self._model = None
        if self.api_key:
            import google.generativeai as genai
            genai.configure(api_key=self.api_key)
            self._model = genai.GenerativeModel(self.model_name)

    def _call(self, prompt: str, retries=3):
        if not self._model:
            raise RuntimeError("GEMINI_API_KEY not set")
        for attempt in range(retries):
            try:
                resp = self._model.generate_content(prompt)
                return resp.text
            except Exception as e:
                msg = str(e)
                if "429" in msg or "quota" in msg.lower() or "rate" in msg.lower():
                    wait = (2 ** attempt) * 2
                    print(f"[Gemini] 429 rate limit, backoff {wait}s (attempt {attempt+1}) model={self.model_name}")
                    time.sleep(wait)
                    continue
                if attempt == retries-1: raise
                time.sleep(1)
        return ""

    def extract_opportunity(self, url, html_text, source_name):
        snippet = html_text[:12000]
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
            cleaned = raw.strip()
            if "```" in cleaned:
                cleaned = cleaned.split("```")[1]
                if cleaned.startswith("json"): cleaned = cleaned[4:]
            j = json.loads(cleaned)
            return j
        except Exception as e:
            print(f"[Gemini extract] JSON parse failed: {e} | raw[:500]={raw[:500]}")
            return {"is_opportunity": False, "raw": raw[:2000]}

    def extract_and_score(self, url, html_text, source_name, profile_summary):
        """Merged extraction + scoring in one call to save quota."""
        snippet = html_text[:12000]
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
            cleaned = raw.strip()
            if "```" in cleaned:
                cleaned = cleaned.split("```")[1]
                if cleaned.startswith("json"): cleaned = cleaned[4:]
            j = json.loads(cleaned)
            if not j.get("is_opportunity"): return j, {}
            scoring = {"score": j.pop("score", 0), "reasons": j.pop("reasons",""), "gaps": j.pop("gaps",[])}
            return j, scoring
        except Exception as e:
            print(f"[Gemini merge] parse fail: {e}, falling back to extract only")
            # Fallback to extract only
            ext = self.extract_opportunity(url, html_text, source_name)
            return ext, {}

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
            cleaned = raw.strip()
            if "```" in cleaned:
                cleaned = cleaned.split("```")[1]
                if cleaned.startswith("json"): cleaned = cleaned[4:]
            return json.loads(cleaned)
        except Exception as e:
            print(f"[Gemini score] parse fail: {e}")
            return {"score": 0, "reasons": "Scoring failed", "gaps": []}

def get_provider(name: str = None) -> AIProvider:
    name = (name or os.getenv("AI_PROVIDER", "gemini")).lower()
    if name == "gemini":
        return GeminiProvider()
    raise ValueError(f"Unknown AI_PROVIDER {name}")
