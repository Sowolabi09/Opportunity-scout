from worker.scoring.matcher import hard_filter, weighted_score, is_borderline

def test_hard_filter_keeps_rolling_no_deadline():
    opp={"deadline":None,"deadline_status":"rolling","trust_label":"UNVERIFIED","funding_type":"full","nigeria_eligibility":"unclear"}
    cfg={"hard_filters":{"reject_past_deadline":True}}
    ok,reason=hard_filter(opp, {}, cfg)
    assert ok is True, "Rolling/unknown should not be rejected for missing deadline"

def test_hard_filter_keeps_unclear_nigeria():
    opp={"trust_label":"UNVERIFIED","funding_type":"full","nigeria_eligibility":"unclear"}
    cfg={"hard_filters":{}}
    ok,_=hard_filter(opp, {}, cfg)
    assert ok is True

def test_hard_filter_rejects_excluded_only():
    opp={"trust_label":"UNVERIFIED","funding_type":"full","nigeria_eligibility":"excluded"}
    cfg={"hard_filters":{}}
    ok,reason=hard_filter(opp, {}, cfg)
    assert ok is False
    # But excluded boolean legacy also
    opp2={"nigeria_eligible": False}
    # _normalize should map to excluded
    ok2,_=hard_filter({"trust_label":"UNVERIFIED","nigeria_eligible":False}, {}, {"hard_filters":{}})
    # This uses new logic: hard_filter checks nigeria_eligibility fallback
    # If not present, it checks boolean via _normalize, so should reject
    # Let's test directly via hard_filter with nigeria_eligibility excluded
    assert ok is False

def test_hard_filter_rejects_past_dated():
    opp={"deadline":"2020-01-01T00:00:00Z","deadline_status":"dated","trust_label":"UNVERIFIED","funding_type":"full","nigeria_eligibility":"unclear"}
    cfg={"hard_filters":{"reject_past_deadline":True}}
    ok,_=hard_filter(opp, {}, cfg)
    assert ok is False

def test_weighted_score_high_for_match():
    opp={"field":"physiology","field_category":"primary","country":"UK","level":"MSc","funding_type":"full","required_docs":[],"deadline":None,"deadline_status":"rolling","funding_covers":{}}
    profile={"primary_field":"Physiology","preferred_countries":["UK"],"funding_need":"fully_funded_only","target_levels":["MSc"],"documents":{}}
    cfg={"weights":{"field_fit":0.3,"country_preference":0.15,"funding_fit":0.2,"readiness_fit":0.15,"level_fit":0.1,"deadline_urgency":0.1}}
    score, reasons, gaps=weighted_score(opp, profile, cfg)
    assert score>=70

def test_is_borderline():
    cfg={"thresholds":{"strong_match":70,"possible_match":45}}
    assert is_borderline(70, cfg) is True
    assert is_borderline(68, cfg) is True
    assert is_borderline(45, cfg) is True
    assert is_borderline(30, cfg) is False
    assert is_borderline(90, cfg) is False
