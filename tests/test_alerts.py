from worker.alerts.emailer import strong_match_subject, opportunity_card_html
from worker.alerts.telegram import strong_match_message

def test_subject_format():
    opp={"deadline":"2026-12-15T00:00:00Z","funding_type":"full","level":"PhD","field":"physiology","country":"UK","title":"Gates Cambridge PhD"}
    subj=strong_match_subject(opp)
    assert subj.startswith("Closes 2026-12-15:")
    assert "UK" in subj

def test_telegram_message_contains_link():
    opp={"title":"T","funder":"F","country":"UK","level":"MSc","funding_type":"full","deadline":"2026-12-01","trust_label":"VERIFIED","match_score":88,"match_reasons":"Great fit","official_link":"https://example.com"}
    msg=strong_match_message(opp)
    assert "https://example.com" in msg
    assert "88" in msg

def test_card_html_has_trust():
    opp={"title":"T","funder":"F","host":"H","country":"UK","level":"MSc","field":"physiology","funding_type":"full","funding_covers":{"tuition":True},"trust_label":"VERIFIED","match_score":90,"match_reasons":"Good","deadline":"2026-12-01","official_link":"https://example.com","source_id":"test","gap_list":[],"cost_breakdown":{},"trust_reasons":["official domain"]}
    html=opportunity_card_html(opp)
    assert "VERIFIED" in html
    assert "official domain" in html or "90" in html
