from worker.verification.trust import verify, domain_is_trusted, is_brand_impersonation

def test_verified_on_trusted_domain_exact():
    opp={"title":"Chevening","funder":"Chevening","official_link":"https://www.chevening.org/scholarships/","deadline":"2026-12-01"}
    label, reasons=verify(opp, "https://www.chevening.org/scholarships/", "Apply via chevening.org")
    assert label=="VERIFIED"
    assert domain_is_trusted("https://www.chevening.org/scholarships/") is True
    assert domain_is_trusted("https://chevening.org") is True

def test_brand_impersonation_flagged_not_verified():
    opp={"title":"Fake Chevening","funder":"Chevening","official_link":"https://chevening-apply.com/scholarship","deadline":"2026-12-01"}
    label, reasons=verify(opp, "https://chevening-apply.com/scholarship", "Apply now")
    assert is_brand_impersonation("https://chevening-apply.com/scholarship") is True
    assert label=="UNVERIFIED"
    assert any("brand" in r.lower() for r in reasons)

def test_suspicious_only_for_individual_payments():
    opp={"title":"Fake Grant","official_link":"https://example.com","deadline":"2026-12-01","deadline_status":"dated"}
    label, reasons=verify(opp, "https://example.com", "Pay $500 via Western Union to secure your award whatsapp +123456789012")
    assert label=="SUSPICIOUS"

def test_official_fee_not_suspicious():
    opp={"title":"Cambridge","funder":"Cambridge","official_link":"https://www.cam.ac.uk/apply","deadline":"2026-12-01","deadline_status":"dated"}
    label, reasons=verify(opp, "https://www.cam.ac.uk/apply", "Application fee £50 payable via official university portal")
    assert label=="VERIFIED"
    assert not any("SUSPICIOUS" in r for r in reasons)
    # Fee should be noted but not suspicious
    assert any("application fee" in r.lower() for r in reasons)

def test_unverified_no_deadline_but_rolling():
    opp={"title":"Some Scholarship","official_link":"https://unknown-blog.com/post","deadline":None,"deadline_status":"rolling"}
    label, reasons=verify(opp, "https://unknown-blog.com/post", "Great scholarship")
    assert label=="UNVERIFIED"
