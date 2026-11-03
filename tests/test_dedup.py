from worker.utils.dedup import dedup_hash, canonical_url, normalize_text

def test_dedup_deterministic():
    h1=dedup_hash("DAAD Scholarship", "DAAD", 2027, "https://daad.de/apply")
    h2=dedup_hash("daAD scholarship ", "  DAAD ", 2027, "https://daad.de/apply/")
    assert h1==h2, "normalize should make these equal"

def test_dedup_same_title_funder_year_url_but_deadline_changed_is_same_hash():
    """Deadline change is an update, not new record — hash must NOT include deadline"""
    h1=dedup_hash("Title", "Funder", 2027, "https://example.com/a")
    h2=dedup_hash("Title", "Funder", 2027, "https://example.com/a?utm_source=foo")
    # Same intake_year + canonical URL -> same hash even if deadline differs (deadline not in hash)
    assert h1==h2

def test_dedup_different_intake_year_is_different():
    h1=dedup_hash("Title", "Funder", 2027, "https://example.com/a")
    h2=dedup_hash("Title", "Funder", 2028, "https://example.com/a")
    assert h1!=h2

def test_canonical_url_strips_tracking_and_www():
    u=canonical_url("https://www.Example.COM/path/?utm_source=foo&fbclid=123")
    assert u=="https://example.com/path"
    u2=canonical_url("https://Example.COM/path/#section")
    assert u2=="https://example.com/path"

def test_content_hash_stable():
    from worker.utils.dedup import content_hash
    assert content_hash("hello") == content_hash("hello")
    assert content_hash("hello") != content_hash("world")
