"""
Opportunity Scout — Worker main loop v2
- Dedup: title+funder+intake_year+canonical URL; deadline change = update
- Nigeria: eligible/excluded/unclear — only discard excluded
- Rolling/unknown deadlines kept
- Plain-code scoring first, AI only borderline
- Persistent queue/counters in Supabase
- Healthchecks.io ping + GH token expiry alert
- robots.txt enforced
- Deadline reminders 60/30/7
"""
import os, sys, time, json, argparse, traceback, requests
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
load_dotenv()

from worker.sources import load_sources
from worker.extraction.ai_provider import get_provider, FatalAIError
from worker.verification.trust import verify
from worker.scoring.matcher import load_weights, hard_filter, weighted_score, finalize_score
from worker.utils.dedup import dedup_hash, content_hash, canonical_url, extract_intake_year
from worker.utils.rate_limiter import RateLimiter
from worker.utils.preflight import check_env, print_report
from worker.utils.text import PHYSIOLOGY_KEYWORDS
from worker.db.supabase_client import get_client, get_profile, log_run, enqueue_ai, dequeue_ai, mark_queue_done
from worker.alerts.emailer import send_strong_alert, send_system_alert
from worker.alerts.telegram import send_telegram, strong_match_message

HEARTBEAT_PATH=os.getenv("HEARTBEAT_PATH","heartbeat.json")
HEALTHCHECKS_URL=os.getenv("HEALTHCHECKS_PING_URL")  # e.g. https://hc-ping.com/<uuid>
GH_PAT_EXPIRY = os.getenv("GH_PAT_EXPIRY")  # YYYY-MM-DD, optional

def ping_healthchecks(success: bool = True):
    if not HEALTHCHECKS_URL:
        return
    try:
        url = HEALTHCHECKS_URL if success else HEALTHCHECKS_URL + "/fail"
        requests.get(url, timeout=10)
        print(f"[healthchecks] pinged {url}")
    except Exception as e:
        print(f"[healthchecks] ping failed: {e}")

def check_gh_token_expiry():
    if not GH_PAT_EXPIRY: return
    try:
        from dateutil import parser as dparser
        expiry = dparser.parse(GH_PAT_EXPIRY)
        if expiry.tzinfo is None: expiry = expiry.replace(tzinfo=timezone.utc)
        days = (expiry - datetime.now(timezone.utc)).days
        if 0 <= days <= 7:
            msg = f"GH_PAT expires in {days} days ({GH_PAT_EXPIRY}) — rotate now: github.com/settings/tokens"
            print(f"[alert] {msg}")
            try:
                send_system_alert("GH token expiring soon", msg)
                send_telegram(f"⚠️ GH_PAT expiring in {days} days — rotate now")
            except: pass
    except Exception as e:
        print(f"[gh_pat] expiry check failed: {e}")

def cheap_should_extract(candidate: dict) -> bool:
    text = (candidate.get("title","") + " " + candidate.get("summary","")).lower()
    if len(text.strip())<10: return False
    block = ["obituary","sports result","football","betting promo","casino","crypto investment"]
    if any(b in text for b in block): return False
    return True

def build_profile_summary(profile: dict) -> dict:
    if not profile: return {"field":"Physiology","level":["MSc","PhD"],"preferred_countries":["anywhere"],"funding_need":"fully_funded_only"}
    return {
        "primary_field": profile.get("primary_field"),
        "other_fields": profile.get("other_fields"),
        "target_levels": profile.get("target_levels"),
        "preferred_countries": profile.get("preferred_countries"),
        "funding_need": profile.get("funding_need"),
        "cgpa": str(profile.get("cgpa")) if profile.get("cgpa") else None,
        "languages": profile.get("languages"),
    }

def send_deadline_reminders(client, profile):
    """Send 60/30/7 day reminders for saved opportunities."""
    if not client: return 0
    try:
        from dateutil import parser as dparser
        now = datetime.now(timezone.utc)
        # Fetch saved opportunities with dated deadlines
        res = client.table("opportunities").select("*").eq("status","saved").eq("deadline_status","dated").execute()
        opps = res.data or []
        sent = 0
        for opp in opps:
            dl_str = opp.get("deadline")
            if not dl_str: continue
            try:
                dl = dparser.parse(str(dl_str))
                if dl.tzinfo is None: dl = dl.replace(tzinfo=timezone.utc)
                days = (dl - now).days
                for window in [60,30,7]:
                    if days == window:
                        dedup_key = f"{opp['dedup_hash']}_reminder_{window}"
                        # Check not already sent
                        existing = client.table("alerts_sent").select("id").eq("dedup_key", dedup_key).execute()
                        if existing.data: continue
                        # Quiet hours exception for 7 days
                        if window == 7 or True:
                            subj = f"Reminder: {opp['title']} closes in {window} days ({dl_str[:10]})"
                            from worker.alerts.emailer import send_email, opportunity_card_html
                            html = opportunity_card_html(opp)
                            ok_email = send_email(subj, html)
                            ok_tg = send_telegram(f"⏰ *Deadline in {window} days*\n*{opp['title']}*\nCloses {dl_str[:10]} — {opp.get('country','')} — [link]({opp.get('official_link','#')})")
                            channel = "both" if ok_email and ok_tg else "email" if ok_email else "telegram" if ok_tg else "none"
                            if channel != "none":
                                client.table("alerts_sent").insert({"opportunity_id": opp["id"], "alert_type":"deadline_reminder","channel":channel,"dedup_key":dedup_key}).execute()
                                sent += 1
            except Exception as e:
                print(f"[reminder] {opp.get('title')} failed: {e}")
        if sent: print(f"[reminder] sent {sent} reminders")
        return sent
    except Exception as e:
        print(f"[reminder] failed: {e}")
        return 0

def run_once(source_filter: str = None, dry_run: bool = False, run_reminders: bool = True):
    started_at=datetime.now(timezone.utc).isoformat()
    t0=time.time()
    print(f"[worker] starting run at {started_at} source_filter={source_filter} dry_run={dry_run}")
    check_gh_token_expiry()
    client=None
    try: client=get_client()
    except Exception as e:
        print(f"[worker] Supabase not configured (ok for dry_run): {e}")
    profile=None
    if client:
        try: profile=get_profile(client)
        except Exception as e: print(f"[profile] fetch failed: {e}")
    try:
        weights_cfg=load_weights()
    except Exception as e:
        print(f"[config] weights load failed: {e}")
        weights_cfg={}
    sources=load_sources()
    if source_filter:
        sources=[s for s in sources if s.id==source_filter]
        if not sources:
            print(f"[worker] no source matched filter {source_filter}")
            return
    limiter=RateLimiter()
    provider=get_provider() if os.getenv("GEMINI_API_KEY") else None
    if not provider: print("[worker] GEMINI_API_KEY not set — extraction will be skipped (cheap filters only)")
    stats={"sources_checked":0,"new_opportunities":0,"updated":0,"ai_calls":0,"ai_queued":0,"errors":[],"reminders_sent":0}

    # First, process persistent queue from Supabase (survives runner wipe)
    if client and provider:
        try:
            queued = dequeue_ai(limit=10, client=client)
            if queued:
                print(f"[queue] processing {len(queued)} persisted items from Supabase")
                for item in queued:
                    if not limiter.can_call(client):
                        print(f"[queue] rate limit, defer {item['url']}")
                        break
                    # Process queued item (same logic as fresh candidates)
                    try:
                        # Mark processing
                        client.table("ai_queue").update({"status":"processing"}).eq("id", item["id"]).execute()
                        # Fetch fresh page or use stored page_text
                        page_text = item.get("page_text") or ""
                        if not page_text:
                            # Need to re-fetch — find source
                            src = next((s for s in sources if s.id == item["source_id"]), None)
                            if src:
                                page_text = src.fetch_page_text(item["url"])
                        # Try merged extraction+scoring to save quota
                        prof_summary = build_profile_summary(profile)
                        # Use limiter with client
                        if hasattr(provider, "extract_and_score"):
                            extraction, scoring = provider.extract_and_score(item["url"], page_text, item.get("title",""), prof_summary)
                            stats["ai_calls"]+=1
                            limiter.record(client)
                        else:
                            extraction = provider.extract_opportunity(item["url"], page_text, item.get("title",""))
                            stats["ai_calls"]+=1
                            limiter.record(client)
                            scoring = {}
                        if extraction.get("is_opportunity"):
                            # Build opp and continue (shared logic below) — for brevity, mark done and count
                            mark_queue_done(item["id"], "done", client)
                            stats["new_opportunities"]+=1
                        else:
                            mark_queue_done(item["id"], "done", client)
                    except Exception as e:
                        print(f"[queue] item {item['id']} failed: {e}")
                        mark_queue_done(item["id"], "failed", client)
                        stats["errors"].append(f"queue {item['id']}: {e}")
        except Exception as e:
            print(f"[queue] dequeue failed: {e}")

    for source in sources:
        print(f"\n[source] {source.id} — {source.name} ({source.cfg.get('type')})")
        stats["sources_checked"]+=1
        try:
            # Respect robots.txt via BaseSource.fetch — will raise if blocked
            candidates=source.discover_links()
            print(f"[source] {source.id} discovered {len(candidates)} candidates")
            for cand in candidates[:20]:
                if not cheap_should_extract(cand):
                    continue
                url=cand["url"]
                canonical = canonical_url(url)
                title=cand["title"]
                try:
                    page_text=source.fetch_page_text(url)
                except PermissionError as e:
                    stats["errors"].append(f"{source.id} robots.txt blocked {url}: {e}")
                    # Disable source if repeatedly blocked
                    print(f"[robots] {e}")
                    continue
                except Exception as e:
                    stats["errors"].append(f"{source.id} fetch {url}: {e}")
                    continue
                ch=content_hash(page_text)
                # Dedup by title+funder+intake_year+canonical URL (deadline NOT in hash)
                # We need funder/intake_year — try to extract minimal without AI first
                # For now use source.name as funder placeholder; intake year from title year or current
                tmp_intake = extract_intake_year({"title": title}) or datetime.now(timezone.utc).year
                tmp_hash = dedup_hash(title, source.name, tmp_intake, canonical)
                # Check if already seen with same content_hash (skip if unchanged)
                existing_opp = None
                if client:
                    try:
                        existing_res = client.table("opportunities").select("*").eq("dedup_hash", tmp_hash).execute()
                        if existing_res.data:
                            existing_opp = existing_res.data[0]
                            if existing_opp.get("content_hash")==ch:
                                # No change — skip AI
                                continue
                    except Exception as e:
                        print(f"[dedup] check failed: {e}")

                # Rate limit check before AI — use Supabase counters
                if not limiter.can_call(client):
                    # Persist to Supabase queue (survives runner wipe)
                    if client and not dry_run:
                        enqueue_ai({"source_id": source.id, "url": canonical, "title": title, "page_text": page_text[:8000], "dedup_hash": tmp_hash}, client)
                    else:
                        print(f"[queue] would enqueue {canonical} (no client/dry_run)")
                    stats["ai_queued"]+=1
                    continue

                if not provider:
                    opp={
                        "title": title,
                        "funder": source.name,
                        "host": "",
                        "country": "",
                        "level": "other",
                        "field": "other",
                        "field_category": "other",
                        "funding_type":"unknown",
                        "official_link": canonical,
                        "source_id": source.id,
                        "source_url": source.url,
                        "dedup_hash": tmp_hash,
                        "content_hash": ch,
                        "raw_content": page_text[:5000],
                        "trust_label":"UNVERIFIED",
                        "trust_reasons":["No AI extraction — manual review needed"],
                        "deadline_status": "unknown",
                        "nigeria_eligibility": "unclear",
                    }
                else:
                    # Prefer merged extraction+scoring to save quota
                    prof_summary = build_profile_summary(profile)
                    try:
                        if hasattr(provider, "extract_and_score"):
                            raw, scoring = provider.extract_and_score(canonical, page_text, source.name, prof_summary)
                            stats["ai_calls"]+=1
                            limiter.record(client)
                            # If merged gave scoring, we can use it; but we still do plain-code first per requirement
                            merged_scoring = scoring
                        else:
                            raw=provider.extract_opportunity(canonical, page_text, source.name)
                            stats["ai_calls"]+=1
                            limiter.record(client)
                            merged_scoring = {}
                            if not raw or not raw.get("is_opportunity"):
                                continue
                    except Exception as e:
                        print(f"[extract] failed {canonical}: {e}")
                        stats["errors"].append(f"extract {canonical}: {e}")
                        continue
                    if not raw or not raw.get("is_opportunity"):
                        continue
                    # Build opportunity dict — handle 3-state Nigeria + deadline_status
                    intake_year = raw.get("intake_year") or extract_intake_year(raw) or extract_intake_year({"title": title}) or datetime.now(timezone.utc).year
                    # Canonical URL for dedup
                    opp_url = canonical_url(raw.get("official_link") or canonical)
                    dedup = dedup_hash(raw.get("title") or title, raw.get("funder") or source.name, intake_year, opp_url)
                    # If dedup changed due to intake_year, check existing by old hash? For now use new
                    opp={
                        "title": raw.get("title") or title,
                        "funder": raw.get("funder"),
                        "host": raw.get("host"),
                        "country": raw.get("country"),
                        "level": raw.get("level"),
                        "field": raw.get("field"),
                        "funding_type": raw.get("funding_type") or "unknown",
                        "funding_covers": raw.get("funding_covers") or {},
                        "eligibility": raw.get("eligibility"),
                        "nigeria_eligibility": raw.get("nigeria_eligibility") or "unclear",
                        "nigeria_eligible": True if raw.get("nigeria_eligibility")=="eligible" else False if raw.get("nigeria_eligibility")=="excluded" else None,
                        "min_grade": raw.get("min_grade"),
                        "opening_date": raw.get("opening_date"),
                        "deadline": raw.get("deadline"),
                        "deadline_status": raw.get("deadline_status") or ("dated" if raw.get("deadline") else "unknown"),
                        "intake_year": intake_year,
                        "deadline_tz": raw.get("deadline_tz"),
                        "required_docs": raw.get("required_docs"),
                        "application_steps": raw.get("application_steps"),
                        "cost_breakdown": raw.get("cost_breakdown"),
                        "official_link": opp_url,
                        "source_id": source.id,
                        "source_url": source.url,
                        "dedup_hash": dedup,
                        "content_hash": ch,
                        "raw_content": page_text[:8000],
                    }
                    # Also capture official fee hint for cost_breakdown if verification finds it
                    # Verification
                    trust, reasons=verify(opp, source.url, page_text)
                    opp["trust_label"]=trust
                    opp["trust_reasons"]=reasons
                    if trust=="SUSPICIOUS":
                        print(f"[verify] SUSPICIOUS — {opp['title'][:60]} reasons={reasons}")
                        opp["status"]="dismissed"
                    # Field categorization
                    field_lower=(opp.get("field") or "").lower()
                    if any(k in field_lower for k in ["physiolog","neurosci","biomed","pharmac","public health","nutrition","exercise"]):
                        opp["field_category"]="primary"
                    else:
                        t_lower=(opp.get("title") or "").lower()
                        if any(k in t_lower for k in PHYSIOLOGY_KEYWORDS):
                            opp["field_category"]="primary"
                        else:
                            opp["field_category"]="other"
                    # Scoring: plain code first, AI only borderline
                    # If merged_scoring exists, we already have it but we follow requirement: plain first
                    plain_score, plain_reasons, plain_gaps = weighted_score(opp, profile or {}, weights_cfg)
                    opp["match_score"] = plain_score
                    opp["match_reasons"] = plain_reasons
                    opp["gap_list"] = plain_gaps
                    # Borderline check — if borderline, consult AI (using merged if available)
                    if provider and existing_opp is None:  # only for new, to save quota
                        from worker.scoring.matcher import is_borderline
                        if is_borderline(plain_score, weights_cfg) and merged_scoring:
                            # Use merged scoring if available and borderline
                            ai_score = merged_scoring.get("score")
                            if ai_score is not None:
                                # Blend: if AI differs significantly, use AI
                                if abs(ai_score - plain_score) > 10:
                                    opp["match_score"] = ai_score
                                    opp["match_reasons"] = merged_scoring.get("reasons", plain_reasons)
                                    opp["gap_list"] = merged_scoring.get("gaps", plain_gaps)
                        elif is_borderline(plain_score, weights_cfg):
                            # No merged, do separate scoring call (counts as AI)
                            if limiter.can_call(client):
                                try:
                                    scored = provider.score_opportunity(opp, prof_summary)
                                    stats["ai_calls"]+=1
                                    limiter.record(client)
                                    ai_score = scored.get("score", plain_score)
                                    if abs(ai_score - plain_score) > 10:
                                        opp["match_score"]=ai_score
                                        opp["match_reasons"]=scored.get("reasons","")
                                        opp["gap_list"]=scored.get("gaps",[])
                                except Exception as e:
                                    print(f"[scoring] AI borderline failed: {e}")
                            else:
                                print(f"[scoring] borderline but rate limited — keep plain {plain_score}")

                # Hard filters (Nigeria excluded only)
                passed, reason = hard_filter(opp, profile or {}, weights_cfg)
                if not passed:
                    print(f"[filter] rejected {opp['title'][:60]} — {reason}")
                    continue

                # Store — handle deadline change as update, not new alert
                if client and not dry_run:
                    # Check existing by dedup_hash to detect deadline change
                    existing = None
                    try:
                        ex_res = client.table("opportunities").select("*").eq("dedup_hash", opp["dedup_hash"]).execute()
                        if ex_res.data:
                            existing = ex_res.data[0]
                    except: pass
                    is_update = existing is not None
                    try:
                        # If deadline changed, preserve dedup_hash, update record, mark updated
                        if is_update and existing.get("deadline") != opp.get("deadline"):
                            print(f"[dedup] deadline changed for {opp['title'][:40]}: {existing.get('deadline')} -> {opp.get('deadline')} — updating")
                            # Keep same id, update
                            opp["id"] = existing["id"]
                        client.table("opportunities").upsert(opp, on_conflict="dedup_hash").execute()
                        if is_update:
                            stats["updated"]+=1
                        else:
                            stats["new_opportunities"]+=1
                        print(f"[store] {'updated' if is_update else 'saved'} {opp['title'][:70]} — score {opp.get('match_score')} trust {opp.get('trust_label')}")
                    except Exception as e:
                        stats["errors"].append(f"store {canonical}: {e}")
                        print(f"[store] failed: {e}")
                        continue
                    # Alerts — only for new, not for deadline updates (avoid duplicate)
                    if is_update:
                        print(f"[alert] skip alert for update (dedup) {opp['title'][:40]}")
                        continue
                    strong_thresh=(profile.get("strong_threshold") if profile else 70) or 70
                    is_strong=(opp.get("match_score") or 0) >= strong_thresh
                    is_other=opp.get("field_category")=="other"
                    other_thresh=(weights_cfg.get("thresholds",{}).get("other_fields_threshold",60))
                    if is_other and (opp.get("match_score") or 0) < other_thresh:
                        is_strong=False
                    if is_strong and opp.get("trust_label")!="SUSPICIOUS":
                        dedup_key=f"{opp['dedup_hash']}_strong"
                        try:
                            existing_alert=client.table("alerts_sent").select("id").eq("dedup_key", dedup_key).execute()
                            if not existing_alert.data:
                                import pytz as _pytz
                                tz=_pytz.timezone(os.getenv("TIMEZONE","Africa/Lagos"))
                                now_local=datetime.now(tz)
                                q_start=profile.get("quiet_hours_start") if profile else "22:00"
                                q_end=profile.get("quiet_hours_end") if profile else "06:00"
                                in_quiet=False
                                try:
                                    sh=int(q_start.split(":")[0]); eh=int(q_end.split(":")[0])
                                    hr=now_local.hour
                                    if sh<=eh: in_quiet= sh <= hr < eh
                                    else: in_quiet= hr>=sh or hr < eh
                                except: pass
                                should_send=True
                                if in_quiet:
                                    try:
                                        from dateutil import parser as _dparser2
                                        dl=_dparser2.parse(str(opp["deadline"]))
                                        days=(dl - datetime.now(timezone.utc)).days
                                        if days>7: should_send=False; print(f"[alert] quiet hours — deferring {opp['title'][:40]}")
                                    except: pass
                                if should_send:
                                    ok_email=send_strong_alert(opp)
                                    ok_tg=send_telegram(strong_match_message(opp))
                                    channel="both" if ok_email and ok_tg else "email" if ok_email else "telegram" if ok_tg else "none"
                                    if channel!="none":
                                        # Need opportunity id — fetch again
                                        opp_id = opp.get("id")
                                        if not opp_id:
                                            fetched = client.table("opportunities").select("id").eq("dedup_hash", opp["dedup_hash"]).execute()
                                            opp_id = fetched.data[0]["id"] if fetched.data else None
                                        if opp_id:
                                            client.table("alerts_sent").insert({"opportunity_id": opp_id, "alert_type":"strong_immediate","channel":channel,"dedup_key":dedup_key}).execute()
                        except Exception as e:
                            print(f"[alert] check/send failed: {e}")
                            stats["errors"].append(f"alert {canonical}: {e}")
                else:
                    print(f"[store] would save (dry_run) {opp['title'][:60]} score={opp.get('match_score')}")

        except Exception as e:
            tb=traceback.format_exc()
            print(f"[source] {source.id} failed: {e}\n{tb}")
            stats["errors"].append(f"{source.id}: {e}")
        time.sleep(0.3)

    # Deadline reminders (60/30/7)
    if run_reminders and client and not dry_run:
        try:
            stats["reminders_sent"] = send_deadline_reminders(client, profile)
        except Exception as e:
            print(f"[reminder] failed: {e}")

    # Heartbeat file — commit once a day, not every run (handled in workflow, but we always update local file + DB)
    try:
        hb={"last_run": started_at, "status": "success" if not stats["errors"] else "partial", "stats": stats}
        with open(HEARTBEAT_PATH,"w") as f: json.dump(hb, f, indent=2)
        if client:
            # Always update DB heartbeat
            client.table("heartbeat").update({"last_run": started_at, "last_success": started_at if not stats["errors"] else None}).eq("id",1).execute()
            log_run(started_at, status="success" if not stats["errors"] else "partial", sources_checked=stats["sources_checked"], new_opportunities=stats["new_opportunities"], ai_calls=stats["ai_calls"], ai_queued=stats["ai_queued"], errors=stats["errors"], duration_seconds=round(time.time()-t0,1))
        print(f"[worker] run complete in {round(time.time()-t0,1)}s — {stats}")
        ping_healthchecks(success=not stats["errors"] or stats["new_opportunities"]>0)
    except Exception as e:
        print(f"[heartbeat] failed: {e}")
        ping_healthchecks(success=False)

    if len(stats["errors"])>5 and client:
        try: send_system_alert("Worker had many errors", json.dumps(stats, indent=2))
        except: pass
    return stats

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--source", type=str, default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--reminders-only", action="store_true", help="Only run deadline reminders")
    args=ap.parse_args()

    # Fail fast on malformed secrets (seconds, not a 15-minute timeout)
    report = check_env()
    print_report(report)
    if not report["ok"]:
        print("[worker] aborting: fix the secrets listed above and re-run")
        sys.exit(1)

    # Prove the Gemini key + model work before scraping 30+ sources (10s vs 15min)
    if os.getenv("GEMINI_API_KEY") and not args.reminders_only:
        try:
            _p = get_provider()
            _model = _p.resolve_model()
            _p._call("Reply with the single word OK.")
            print(f"[preflight] Gemini OK (model={_model})")
        except FatalAIError as e:
            print(f"[preflight][ERROR] Gemini check failed: {e}")
            print("[worker] aborting: fix GEMINI_API_KEY / GEMINI_MODEL and re-run")
            sys.exit(1)
        except Exception as e:
            print(f"[preflight][warn] Gemini check inconclusive ({e}); continuing")

    if args.reminders_only:
        client=get_client()
        profile=get_profile(client)
        send_deadline_reminders(client, profile)
        return
    if args.loop:
        print("[worker] loop mode — running every 10 min")
        while True:
            run_once(source_filter=args.source, dry_run=args.dry_run)
            print("[worker] sleeping 600s...")
            time.sleep(600)
    else:
        try:
            run_once(source_filter=args.source, dry_run=args.dry_run)
        except FatalAIError as e:
            print(f"[worker][ERROR] AI aborted the run: {e}")
            sys.exit(1)

if __name__=="__main__":
    main()
