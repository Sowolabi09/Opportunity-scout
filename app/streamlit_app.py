"""
Opportunity Scout — Streamlit Dashboard
Login → Profile → Dashboard (filters, save/dismiss/apply, deadline tracker, gap checklist)
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import streamlit as st
import pandas as pd
from datetime import datetime, timezone, date
from dotenv import load_dotenv
load_dotenv()

from worker.db.supabase_client import get_client, get_profile, upsert_profile
from worker.sources import load_sources

st.set_page_config(page_title="Opportunity Scout", page_icon="🎓", layout="wide", initial_sidebar_state="expanded")

# ── Simple auth ──
def check_auth():
    pw = os.getenv("DASHBOARD_PASSWORD")
    if not pw:
        try:
            pw = st.secrets.get("DASHBOARD_PASSWORD", None)
        except Exception:
            pw = None
    if not pw:
        return True # no password set — allow (dev)
    if "authenticated" not in st.session_state:
        st.session_state.authenticated=False
    if not st.session_state.authenticated:
        st.title("🔐 Opportunity Scout — Login")
        st.info("This dashboard is private. Enter the password set in Streamlit Secrets / env DASHBOARD_PASSWORD.")
        with st.form("login"):
            username=st.text_input("Username (any)")
            password=st.text_input("Password", type="password")
            if st.form_submit_button("Log in"):
                if password==pw:
                    st.session_state.authenticated=True
                    st.rerun()
                else:
                    st.error("Wrong password")
        st.stop()
    return True

check_auth()

# ── Helpers ──
@st.cache_resource
def supabase():
    try: return get_client()  # service_role only — RLS has no anon policies (service_role bypasses RLS)
    except Exception as e:
        st.error(f"Supabase not configured (need SUPABASE_SERVICE_ROLE_KEY): {e}")
        return None
    # Note: dashboard is server-side Python on Streamlit Cloud, so service key never leaves server.
    # Access is gated by DASHBOARD_PASSWORD login above.

client = supabase()

def _profile_or_empty():
    if not client: return {}
    try:
        p=get_profile(client)
        return p or {}
    except: return {}

# ── Sidebar ──
with st.sidebar:
    st.title("🎓 Opportunity Scout")
    st.caption("Physiology • Always-on")
    page=st.radio("Navigate", ["Dashboard","Profile / Settings","Sources & Health","Help"], label_visibility="collapsed")
    st.divider()
    if client:
        try:
            hb=client.table("heartbeat").select("*").limit(1).execute()
            if hb.data:
                last=hb.data[0].get("last_run","?")
                st.caption(f"🟢 Worker last run: {last}")
            else:
                st.caption("⚪ No heartbeat yet")
        except: st.caption("⚪ Heartbeat unavailable")
    if st.button("Logout"):
        st.session_state.authenticated=False
        st.rerun()

# ══════════════════════════════════════════════
if page=="Profile / Settings":
    st.header("👤 Your Profile & Settings")
    st.info("Only public profile summary (field, level, countries, funding need) is sent to Gemini. Never put passport numbers or bank details here. CV is stored in Supabase, not sent to AI unless you choose.")

    profile=_profile_or_empty()
    with st.form("profile_form"):
        c1,c2=st.columns(2)
        with c1:
            st.subheader("Academic")
            course=st.text_input("Course", value=profile.get("course") or "Physiology")
            academic_year=st.text_input("Year / Level", value=profile.get("academic_year") or "300 Level")
            expected_grad=st.date_input("Expected graduation", value=date.fromisoformat(profile["expected_graduation"]) if profile.get("expected_graduation") else date(2027,6,1))
            cgpa=st.number_input("CGPA", value=float(profile.get("cgpa") or 4.2), min_value=0.0, max_value=5.0, step=0.1)
            cgpa_scale=st.selectbox("Scale", [5.0,4.0,7.0], index=0 if (profile.get("cgpa_scale")==5.0 or not profile.get("cgpa_scale")) else 1)
            research_exp=st.text_area("Research experience", value=profile.get("research_experience") or "")
            projects=st.text_area("Projects", value=profile.get("projects") or "")
            publications=st.text_area("Publications (if any)", value=profile.get("publications") or "")
            lab_skills=st.text_input("Lab skills (comma-separated)", value=", ".join(profile.get("lab_skills") or []))

        with c2:
            st.subheader("Goals")
            target_levels=st.multiselect("Target level", ["MSc","PhD","research_internship","fellowship","exchange"], default=profile.get("target_levels") or ["MSc","PhD"])
            preferred_countries=st.multiselect("Preferred countries (leave empty = anywhere)", ["UK","Germany","Netherlands","Sweden","Canada","Australia","USA","Japan","China","South Korea","Switzerland","Nigeria","anywhere"], default=profile.get("preferred_countries") or ["UK","Germany","Canada"])
            target_start=st.date_input("Target start date", value=date.fromisoformat(profile["target_start_date"]) if profile.get("target_start_date") else date(2027,9,1))
            languages=st.text_input("Languages", value=", ".join(profile.get("languages") or ["English"]))
            st.subheader("Fields")
            primary_field=st.text_input("Primary field", value=profile.get("primary_field") or "Physiology")
            other_fields=st.text_input("Other fields you'd consider (comma-separated)", value=", ".join(profile.get("other_fields") or ["Public Health","Neuroscience"]))
            st.subheader("Money")
            funding_need=st.selectbox("Funding I need", ["fully_funded_only","partly_funded_ok","self_funded_ok"], index=["fully_funded_only","partly_funded_ok","self_funded_ok"].index(profile.get("funding_need") or "fully_funded_only"))
            upfront_budget=st.number_input("Upfront budget (USD) for fees/tests/visa", value=float(profile.get("upfront_budget_usd") or 500), min_value=0.0, step=100.0)

        st.subheader("Readiness")
        r1,r2,r3=st.columns(3)
        with r1: ielts_status=st.text_input("IELTS status", value=profile.get("ielts_status") or "not_taken", help="e.g. not_taken, scheduled:2026-06-01, taken:7.0")
        with r2: toefl_status=st.text_input("TOEFL status", value=profile.get("toefl_status") or "")
        with r3: referees=st.number_input("Referees available", value=int(profile.get("referees_available") or 1), min_value=0, max_value=5)

        st.subheader("Documents I have")
        docs=profile.get("documents") or {}
        d1,d2,d3,d4=st.columns(4)
        with d1: has_transcript=st.checkbox("Transcript", value=bool(docs.get("transcript")))
        with d2: has_cv=st.checkbox("CV", value=bool(docs.get("cv")))
        with d3: has_passport=st.checkbox("Passport", value=bool(docs.get("passport")))
        with d4: has_sop=st.checkbox("SOP draft", value=bool(docs.get("sop_draft")))

        st.subheader("CV auto-fill (optional)")
        st.caption("Paste CV text below — we extract skills/projects locally without sending PII to AI. You can also upload a file.")
        cv_text=st.text_area("Paste CV text", value=profile.get("cv_text") or "", height=150)
        cv_file=st.file_uploader("Or upload CV (PDF/TXT)", type=["pdf","txt","docx"])
        if cv_file and not cv_text:
            try:
                cv_text=cv_file.read().decode("utf-8", errors="ignore")
                st.success(f"Loaded {len(cv_text)} chars from upload")
            except:
                st.warning("Could not read file — paste text instead")

        st.subheader("Alert settings")
        a1,a2,a3=st.columns(3)
        with a1: strong_thresh=st.slider("Strong-match threshold", 50, 90, value=int(profile.get("strong_threshold") or 70))
        with a2: receive_possible=st.checkbox("Receive possible-match daily digest", value=bool(profile.get("receive_possible") if profile.get("receive_possible") is not None else True))
        with a3: summary_time=st.text_input("Digest time (Africa/Lagos HH:MM)", value=profile.get("summary_time") or "19:00")
        q1,q2=st.columns(2)
        with q1: quiet_start=st.text_input("Quiet hours start", value=profile.get("quiet_hours_start") or "22:00")
        with q2: quiet_end=st.text_input("Quiet hours end", value=profile.get("quiet_hours_end") or "06:00")

        submitted=st.form_submit_button("💾 Save profile", use_container_width=True, type="primary")
        if submitted:
            data={
                "course": course, "academic_year": academic_year, "expected_graduation": str(expected_grad),
                "cgpa": cgpa, "cgpa_scale": cgpa_scale, "research_experience": research_exp, "projects": projects, "publications": publications,
                "lab_skills": [s.strip() for s in lab_skills.split(",") if s.strip()],
                "target_levels": target_levels, "preferred_countries": preferred_countries, "target_start_date": str(target_start), "languages": [s.strip() for s in languages.split(",") if s.strip()],
                "primary_field": primary_field, "other_fields": [s.strip() for s in other_fields.split(",") if s.strip()],
                "funding_need": funding_need, "upfront_budget_usd": upfront_budget,
                "ielts_status": ielts_status, "toefl_status": toefl_status, "referees_available": referees,
                "documents": {"transcript": has_transcript, "cv": has_cv, "passport": has_passport, "sop_draft": has_sop},
                "cv_text": cv_text[:8000] if cv_text else None,
                "strong_threshold": strong_thresh, "receive_possible": receive_possible, "summary_time": summary_time,
                "quiet_hours_start": quiet_start, "quiet_hours_end": quiet_end,
            }
            if client:
                try:
                    upsert_profile(data, client)
                    st.success("Profile saved ✅ — scoring will use your new settings on next worker run")
                except Exception as e:
                    st.error(f"Save failed: {e}")
            else:
                st.warning("No DB — profile not persisted (dev mode)")

elif page=="Dashboard":
    st.header("🔎 Opportunities")
    if not client:
        st.warning("Supabase not configured — showing demo data. Configure secrets to go live.")
        demo=pd.DataFrame([
            {"title":"Gates Cambridge Scholarship — PhD Physiology","funder":"Gates Cambridge","country":"UK","level":"PhD","field":"physiology","funding_type":"full","deadline":"2027-01-07","trust_label":"VERIFIED","match_score":88,"gap_list":["Needs IELTS 7.0"],"field_category":"primary"},
            {"title":"DAAD EPOS — MSc Public Health","funder":"DAAD","country":"Germany","level":"MSc","field":"public health","funding_type":"full","deadline":"2026-12-01","trust_label":"VERIFIED","match_score":76,"gap_list":[],"field_category":"primary"},
            {"title":"Master Data Science Fellowship","funder":"Tech Foundation","country":"USA","level":"MSc","field":"data science","funding_type":"partial","deadline":"2026-11-15","trust_label":"UNVERIFIED","match_score":52,"gap_list":[],"field_category":"other"},
        ])
        opportunities=demo.to_dict("records")
    else:
        # Filters
        f1,f2,f3,f4,f5=st.columns(5)
        with f1: field_filter=st.selectbox("Field", ["All","Primary only","Other fields"], index=0)
        with f2: country_filter=st.text_input("Country (leave empty = all)", value="")
        with f3: level_filter=st.selectbox("Level", ["All","MSc","PhD","fellowship","internship","exchange"], index=0)
        with f4: funding_filter=st.selectbox("Funding", ["All","full","partial","none","unknown"], index=0)
        with f5:
            trust_filter=st.selectbox("Trust", ["All","VERIFIED","UNVERIFIED","SUSPICIOUS"], index=0)
            st.caption("SUSPICIOUS hidden by default")

        show_dismissed=st.checkbox("Show dismissed", value=False)

        try:
            q=client.table("opportunities").select("*").order("deadline", desc=False).limit(200)
            if field_filter=="Primary only": q=q.eq("field_category","primary")
            if field_filter=="Other fields": q=q.eq("field_category","other")
            if country_filter: q=q.ilike("country", f"%{country_filter}%")
            if level_filter!="All": q=q.eq("level", level_filter)
            if funding_filter!="All": q=q.eq("funding_type", funding_filter)
            if trust_filter!="All": q=q.eq("trust_label", trust_filter)
            else: q=q.neq("trust_label","SUSPICIOUS") # hide suspicious by default
            if not show_dismissed: q=q.neq("status","dismissed")
            res=q.execute()
            opportunities=res.data or []
            if not opportunities:
                st.info("No opportunities yet — worker will populate this table. Trigger a manual run from GitHub Actions → Run workflow.")
        except Exception as e:
            st.error(f"Load failed: {e}")
            opportunities=[]

    if opportunities:
        # Tabs
        tab_all, tab_primary, tab_other, tab_deadlines = st.tabs([f"All ({len(opportunities)})", f"Primary — Physiology & related ({len([o for o in opportunities if o.get('field_category')=='primary'])})", f"Other fields ({len([o for o in opportunities if o.get('field_category')=='other'])})", "⏰ Deadline tracker"])
        def render_list(opps, key_prefix):
            for opp in opps:
                score=opp.get("match_score") or 0
                trust=opp.get("trust_label") or "UNVERIFIED"
                color={"VERIFIED":"green","UNVERIFIED":"orange","SUSPICIOUS":"red"}.get(trust,"gray")
                with st.container(border=True):
                    c1,c2=st.columns([3,1])
                    with c1:
                        st.markdown(f"**{opp.get('title','Untitled')}** — {opp.get('funder','')} • {opp.get('country','')} • {opp.get('level','')} • {opp.get('funding_type','')} funded")
                        st.caption(f"Deadline: {str(opp.get('deadline','TBD'))[:10]} • Field: {opp.get('field','')} • Trust: :{color}[{trust}] • Score: {score}/100")
                        if opp.get("gap_list"):
                            st.warning("Gaps: " + "; ".join(opp["gap_list"] if isinstance(opp["gap_list"], list) else [str(opp["gap_list"])]))
                        if opp.get("match_reasons"):
                            st.caption(f"Why matched: {opp['match_reasons']}")
                        if opp.get("official_link"):
                            st.link_button("Official page →", opp["official_link"])
                    with c2:
                        st.metric("Match", f"{score}")
                        # Actions
                        if client:
                            cols=st.columns(3)
                            oid=opp.get("id")
                            with cols[0]:
                                if st.button("Save", key=f"{key_prefix}_save_{oid}", use_container_width=True):
                                    try:
                                        client.table("opportunities").update({"status":"saved"}).eq("id", oid).execute()
                                        st.toast("Saved ✅")
                                        st.rerun()
                                    except Exception as e: st.error(str(e))
                            with cols[1]:
                                if st.button("Dismiss", key=f"{key_prefix}_dismiss_{oid}", use_container_width=True):
                                    try:
                                        client.table("opportunities").update({"status":"dismissed"}).eq("id", oid).execute()
                                        st.toast("Dismissed")
                                        st.rerun()
                                    except Exception as e: st.error(str(e))
                            with cols[2]:
                                if st.button("Applied", key=f"{key_prefix}_applied_{oid}", use_container_width=True):
                                    try:
                                        client.table("opportunities").update({"status":"applied"}).eq("id", oid).execute()
                                        st.toast("Marked as applied 🎉")
                                        st.rerun()
                                    except Exception as e: st.error(str(e))

        with tab_all: render_list(opportunities, "all")
        with tab_primary: render_list([o for o in opportunities if o.get("field_category")=="primary"], "primary")
        with tab_other: render_list([o for o in opportunities if o.get("field_category")=="other"], "other")
        with tab_deadlines:
            df=pd.DataFrame(opportunities)
            if not df.empty and "deadline" in df.columns:
                df["deadline"]=pd.to_datetime(df["deadline"], errors="coerce")
                df=df.dropna(subset=["deadline"]).sort_values("deadline")
                # upcoming 60/30/7
                now=pd.Timestamp.now(tz="UTC")
                for window, label in [(60,"≤60 days"),(30,"≤30 days"),(7,"≤7 days — URGENT")]:
                    subset=df[df["deadline"] <= now + pd.Timedelta(days=window)]
                    st.subheader(label + f" ({len(subset)})")
                    if not subset.empty:
                        st.dataframe(subset[["title","deadline","country","funding_type","trust_label","match_score"]], use_container_width=True, hide_index=True)
                    else:
                        st.caption("None in this window")
                # visual
                try:
                    import plotly.express as px
                    fig=px.scatter(df, x="deadline", y="match_score", color="trust_label", hover_data=["title","country"], title="Deadlines vs Match Score")
                    st.plotly_chart(fig, use_container_width=True)
                except: pass
            else:
                st.info("No deadlines to track yet")

elif page=="Sources & Health":
    st.header("📡 Sources & Worker Health")
    if not client:
        st.warning("No DB — connect Supabase to see live health")
        # Show config sources
        try:
            srcs=load_sources()
            st.dataframe(pd.DataFrame([{"id":s.id,"name":s.name,"type":s.cfg.get("type"),"interval_minutes":s.cfg.get("interval_minutes")} for s in srcs]), use_container_width=True)
        except Exception as e: st.error(str(e))
    else:
        try:
            logs=client.table("run_logs").select("*").order("started_at", desc=True).limit(10).execute()
            st.subheader("Recent runs")
            if logs.data:
                st.dataframe(pd.DataFrame(logs.data), use_container_width=True)
            else:
                st.info("No runs logged yet")

            srcs=client.table("sources").select("*").execute()
            st.subheader("Source health")
            if srcs.data:
                st.dataframe(pd.DataFrame(srcs.data), use_container_width=True)
            else:
                st.info("No source health rows — worker will populate on first run. Config sources:")
                cfgs=load_sources()
                st.dataframe(pd.DataFrame([{"id":s.id,"name":s.name} for s in cfgs]), use_container_width=True)

            st.subheader("Supabase heartbeat")
            hb=client.table("heartbeat").select("*").execute()
            st.json(hb.data)

            if st.button("Trigger manual check (info)"):
                st.info("To trigger worker manually: GitHub → Actions → Scout → Run workflow → workflow_dispatch. Or hit the cron-job.org job URL.")
        except Exception as e:
            st.error(f"Health load failed: {e}")

elif page=="Help":
    st.header("❓ Help")
    st.markdown(open("docs/SETUP.md").read() if os.path.exists("docs/SETUP.md") else "See docs/SETUP.md in the repo")
