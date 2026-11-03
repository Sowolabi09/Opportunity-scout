"""Persistent rate limiter — RPM/RPD via Supabase ai_usage + ai_queue tables."""
import time, os, yaml
from datetime import datetime, timezone

DEFAULT_CONFIG_PATH = "config/ai_limits.yaml"

def load_ai_limits():
    # Prefer env, then config file, then defaults (current limits from AI Studio)
    cfg_path = os.getenv("AI_LIMITS_CONFIG", DEFAULT_CONFIG_PATH)
    try:
        with open(cfg_path) as f:
            cfg = yaml.safe_load(f)
            return cfg.get("gemini", {})
    except:
        pass
    # Fallback defaults — verified Oct 2026: Gemini 2.5 Flash-Lite 30 RPM/1500 RPD, Flash 10-15 RPM/500 RPD
    return {
        "model": os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite"),
        "rpm": int(os.getenv("GEMINI_RPM_LIMIT", "28")),
        "rpd": int(os.getenv("GEMINI_DAILY_BUDGET", "1400")),
        "tpm": 250000,
    }

class RateLimiter:
    """Supabase-backed RPM/RPD — survives runner wipe."""
    def __init__(self, rpm: int = None, rpd: int = None):
        limits = load_ai_limits()
        self.rpm = int(rpm or limits.get("rpm", 28))
        self.rpd = int(rpd or limits.get("rpd", 1400))
        self._local_minute = []  # local fallback if Supabase down

    def can_call(self, client=None) -> bool:
        # Try Supabase first
        if client or os.getenv("SUPABASE_URL"):
            try:
                from worker.db.supabase_client import get_ai_usage
                minute_count, daily_count = get_ai_usage(client)
                if minute_count >= self.rpm: return False
                if daily_count >= self.rpd: return False
                return True
            except Exception as e:
                print(f"[limiter] Supabase check failed, fallback local: {e}")
        # Fallback local
        now = time.time()
        self._local_minute = [t for t in self._local_minute if t > now - 60]
        return len(self._local_minute) < self.rpm

    def record(self, client=None):
        if client or os.getenv("SUPABASE_URL"):
            try:
                from worker.db.supabase_client import increment_ai_usage
                increment_ai_usage(client)
                return
            except Exception as e:
                print(f"[limiter] Supabase increment failed: {e}")
        self._local_minute.append(time.time())

    def wait_time(self, client=None) -> float:
        if client or os.getenv("SUPABASE_URL"):
            try:
                from worker.db.supabase_client import get_ai_usage
                minute_count, _ = get_ai_usage(client)
                if minute_count >= self.rpm:
                    return 60.0
            except: pass
        return 0
