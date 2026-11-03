"""Supabase client — service_role only (RLS enabled, no anon policies)."""
import os, time
from typing import Optional
from supabase import create_client, Client
from dotenv import load_dotenv
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

def get_client(use_service: bool = True) -> Client:
    """Always uses service_role; anon is disabled by RLS. Dashboard is server-side, so this is safe behind DASHBOARD_PASSWORD."""
    if not SUPABASE_URL:
        raise RuntimeError("SUPABASE_URL not set — check .env / GitHub Secrets")
    key = SUPABASE_SERVICE_ROLE_KEY
    if not key:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY not set — RLS requires service key (see HANDOVER: Key rotation)")
    return create_client(SUPABASE_URL, key)

def get_profile(client: Client = None):
    c = client or get_client()
    res = c.table("profiles").select("*").limit(1).execute()
    return res.data[0] if res.data else None

def upsert_profile(data: dict, client: Client = None):
    c = client or get_client()
    existing = get_profile(c)
    if existing:
        data["id"] = existing["id"]
        return c.table("profiles").upsert(data).execute()
    return c.table("profiles").insert(data).execute()

def insert_opportunity(opp: dict, client: Client = None):
    c = client or get_client()
    return c.table("opportunities").upsert(opp, on_conflict="dedup_hash").execute()

def log_run(started_at, **kwargs):
    try:
        c = get_client()
        c.table("run_logs").insert({"started_at": started_at, **kwargs}).execute()
        c.table("heartbeat").update({
            "last_run": started_at,
            "last_success": started_at if kwargs.get("status") in ("success","partial") else None
        }).eq("id", 1).execute()
    except Exception as e:
        print(f"[heartbeat] failed: {e}")

# ── AI Queue persistence ──
def enqueue_ai(item: dict, client: Client = None):
    c = client or get_client()
    try:
        c.table("ai_queue").insert({
            "source_id": item.get("source_id"),
            "url": item.get("url"),
            "title": item.get("title"),
            "page_text": item.get("page_text"),
            "dedup_hash": item.get("dedup_hash"),
            "status": "pending"
        }).execute()
        print(f"[queue] persisted {item.get('url')}")
    except Exception as e:
        print(f"[queue] enqueue failed: {e}")

def dequeue_ai(limit=10, client: Client = None):
    """Fetch pending items (for next run)."""
    c = client or get_client()
    try:
        res = c.table("ai_queue").select("*").eq("status","pending").order("created_at").limit(limit).execute()
        return res.data or []
    except Exception as e:
        print(f"[queue] dequeue failed: {e}")
        return []

def mark_queue_done(queue_id, status="done", client: Client = None):
    c = client or get_client()
    try:
        c.table("ai_queue").update({"status": status}).eq("id", queue_id).execute()
    except Exception as e:
        print(f"[queue] mark failed: {e}")

# ── AI Usage counters (RPM/RPD) persisted ──
def get_ai_usage(client: Client = None):
    """Return (minute_count, daily_count) for current windows."""
    from datetime import datetime, timezone, timedelta
    c = client or get_client()
    now = datetime.now(timezone.utc)
    minute_start = now.replace(second=0, microsecond=0)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        # Use Pacific midnight for RPD (Gemini resets midnight Pacific)
        # For simplicity we use UTC midnight and document it; health check will warn if close to limit.
        m_res = c.table("ai_usage").select("count").eq("window_start", minute_start.isoformat()).eq("window_type","minute").execute()
        d_res = c.table("ai_usage").select("count").eq("window_start", day_start.isoformat()).eq("window_type","day").execute()
        minute_count = m_res.data[0]["count"] if m_res.data else 0
        daily_count = d_res.data[0]["count"] if d_res.data else 0
        return minute_count, daily_count
    except Exception as e:
        print(f"[ai_usage] fetch failed: {e}")
        return 0,0

def increment_ai_usage(client: Client = None):
    from datetime import datetime, timezone
    c = client or get_client()
    now = datetime.now(timezone.utc)
    minute_start = now.replace(second=0, microsecond=0).isoformat()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    for window_start, window_type in [(minute_start,"minute"),(day_start,"day")]:
        try:
            # upsert with increment
            existing = c.table("ai_usage").select("count").eq("window_start", window_start).eq("window_type", window_type).execute()
            if existing.data:
                c.table("ai_usage").update({"count": existing.data[0]["count"]+1}).eq("window_start", window_start).eq("window_type", window_type).execute()
            else:
                c.table("ai_usage").insert({"window_start": window_start, "window_type": window_type, "count": 1}).execute()
        except Exception as e:
            print(f"[ai_usage] increment {window_type} failed: {e}")
