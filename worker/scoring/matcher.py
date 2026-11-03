"""Matching & scoring 0-100 with hard filters + weighted score.

Plain-code scoring is primary. AI is called only for borderline cases.
"""
import yaml, os
from datetime import datetime, timezone
from dateutil import parser as dparser

CONFIG_PATH = os.getenv("SCORING_CONFIG", "config/scoring_weights.yaml")

def load_weights():
    try:
        with open(CONFIG_PATH) as f:
            return yaml.safe_load(f)
    except:
        return {"weights":{"field_fit":0.3,"country_preference":0.15,"funding_fit":0.2,"readiness_fit":0.15,"level_fit":0.1,"deadline_urgency":0.1},"thresholds":{"strong_match":70,"possible_match":45,"other_fields_threshold":60},"hard_filters":{"reject_past_deadline":True,"reject_suspicious":True}}

def _normalize_nigeria(opportunity: dict) -> str:
    """Return eligible|excluded|unclear from either new or old field."""
    val = opportunity.get("nigeria_eligibility")
    if val in ("eligible","excluded","unclear"): return val
    # Backward compat from boolean
    b = opportunity.get("nigeria_eligible")
    if b is True: return "eligible"
    if b is False: return "excluded"
    return "unclear"

def hard_filter(opportunity: dict, profile: dict, weights_cfg: dict) -> tuple[bool, str]:
    hf = weights_cfg.get("hard_filters",{})
    # Nigeria: only discard "excluded", keep eligible and unclear
    nigeria = _normalize_nigeria(opportunity)
    if nigeria == "excluded":
        return False, "Explicitly excludes Nigerian citizens"
    # Past deadline: only reject if deadline_status == dated and deadline passed
    # If rolling/unknown, keep (do not discard)
    if hf.get("reject_past_deadline") and opportunity.get("deadline"):
        if opportunity.get("deadline_status") == "dated":
            try:
                dl = dparser.parse(str(opportunity["deadline"]))
                if dl.tzinfo is None: dl = dl.replace(tzinfo=timezone.utc)
                if dl < datetime.now(timezone.utc):
                    return False, f"Deadline passed: {opportunity['deadline']}"
            except: pass
        # rolling/unknown: never reject for deadline
    # SUSPICIOUS
    if hf.get("reject_suspicious") and opportunity.get("trust_label")=="SUSPICIOUS":
        return False, "Marked SUSPICIOUS — never alert"
    # Funding (legacy)
    if hf.get("funding",{}).get("enforce") if isinstance(hf.get("funding"),dict) else hf.get("enforce",False):
        need = profile.get("funding_need")
        ft = opportunity.get("funding_type")
        if need=="fully_funded_only" and ft in ("none","partial"):
            return False, f"Needs fully funded, opportunity is {ft}"
    elif profile.get("funding_need")=="fully_funded_only" and opportunity.get("funding_type") in ("none",):
        return False, f"Needs fully funded, opportunity is {opportunity.get('funding_type')}"
    return True, ""

def weighted_score(opportunity: dict, profile: dict, cfg: dict) -> tuple[int, str, list]:
    w = cfg.get("weights",{})
    gaps = []
    scores = {}
    primary = (profile.get("primary_field") or "physiology").lower()
    opp_field = (opportunity.get("field") or "other").lower()
    if opp_field in primary or primary in opp_field:
        scores["field_fit"]=100
    elif opp_field in ("physiology","neuroscience","biomedical","pharmacology","public health","nutrition","exercise science","medical sciences"):
        scores["field_fit"]=80
    else:
        opp_field_cat = opportunity.get("field_category")
        scores["field_fit"]= 30 if opp_field_cat=="other" else 50
        if opp_field_cat=="other": gaps.append("Field outside primary — check 'Other fields' tab")
    pref = [c.lower() for c in (profile.get("preferred_countries") or [])]
    opp_country = (opportunity.get("country") or "").lower()
    if not pref or "anywhere" in pref: scores["country_preference"]=80
    elif opp_country in pref: scores["country_preference"]=100
    elif opp_country=="": scores["country_preference"]=60
    else: scores["country_preference"]=40
    need = profile.get("funding_need")
    ft = opportunity.get("funding_type")
    if ft=="full": scores["funding_fit"]=100
    elif ft=="partial" and need!="fully_funded_only": scores["funding_fit"]=70
    elif ft=="partial": scores["funding_fit"]=30
    elif ft=="unknown": scores["funding_fit"]=50
    else: scores["funding_fit"]=20
    readiness=100
    docs = opportunity.get("required_docs") or []
    profile_docs = profile.get("documents") or {}
    if "IELTS" in str(docs) or "TOEFL" in str(docs):
        if profile.get("ielts_status") in (None,"", "not_taken"):
            gaps.append("Needs IELTS/TOEFL — you have not taken it")
            readiness-=20
    if "transcript" in str(docs).lower() and not profile_docs.get("transcript"):
        gaps.append("Needs transcript — not marked as ready")
        readiness-=10
    if "reference" in str(docs).lower():
        need_ref = 2
        have = profile.get("referees_available") or 0
        if have < need_ref:
            gaps.append(f"Needs {need_ref} referees — you have {have}")
            readiness-=10
    scores["readiness_fit"]=max(0,readiness)
    target_levels=[l.lower() for l in (profile.get("target_levels") or [])]
    opp_level=(opportunity.get("level") or "").lower()
    if not target_levels: scores["level_fit"]=70
    elif opp_level in target_levels: scores["level_fit"]=100
    else: scores["level_fit"]=30
    scores["deadline_urgency"]=60
    if opportunity.get("deadline"):
        try:
            dl = dparser.parse(str(opportunity["deadline"]))
            if dl.tzinfo is None: dl = dl.replace(tzinfo=timezone.utc)
            days=(dl - datetime.now(timezone.utc)).days
            if 14 <= days <= 60: scores["deadline_urgency"]=90
            elif 7 <= days <14: scores["deadline_urgency"]=80
            elif days <7 and days>=0: scores["deadline_urgency"]=70
            elif days>60: scores["deadline_urgency"]=50
        except: pass
    elif opportunity.get("deadline_status") in ("rolling","unknown"):
        scores["deadline_urgency"]=65
        gaps.append("Rolling/unknown deadline — apply when ready, but confirm intake year")
    total=sum(scores[k]*w.get(k,0) for k in w)
    if opportunity.get("funding_covers",{}).get("stipend"): total=min(100, total+3)
    reasons=f"Field {scores['field_fit']}, Funding {scores['funding_fit']}, Country {scores['country_preference']}, Readiness {scores['readiness_fit']}, Level {scores['level_fit']}"
    return int(round(total)), reasons, gaps

def is_borderline(score: int, cfg: dict) -> bool:
    """AI is called only for borderline: within 10 of either threshold."""
    strong = cfg.get("thresholds",{}).get("strong_match",70)
    possible = cfg.get("thresholds",{}).get("possible_match",45)
    # Borderline if near either threshold ±10
    return (possible - 10) <= score <= (possible + 10) or (strong - 10) <= score <= (strong + 10)

def finalize_score(opportunity: dict, profile: dict, cfg: dict, provider=None, profile_summary=None) -> tuple[int, str, list]:
    """Plain-code primary; AI only for borderline or if provider can do merged extraction+scoring."""
    plain_score, plain_reasons, plain_gaps = weighted_score(opportunity, profile, cfg)
    if provider and is_borderline(plain_score, cfg):
        try:
            ai_scored = provider.score_opportunity(opportunity, profile_summary or {})
            # If AI disagrees by >15, trust AI; else blend or keep plain
            ai_score = ai_scored.get("score", plain_score)
            if abs(ai_score - plain_score) > 15:
                return ai_score, ai_scored.get("reasons", plain_reasons), ai_scored.get("gaps", plain_gaps)
            else:
                # Use plain but add AI nuance to reasons
                return plain_score, f"{plain_reasons} · AI: {ai_scored.get('reasons','')}", plain_gaps
        except Exception as e:
            print(f"[scoring] borderline AI failed, keep plain: {e}")
            return plain_score, plain_reasons, plain_gaps
    return plain_score, plain_reasons, plain_gaps
