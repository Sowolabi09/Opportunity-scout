"""Deduplication via normalised hash — title + funder + intake year + canonical URL

Deadline changes are treated as updates, not new records (handled in worker/main.py).
"""
import hashlib
import re
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

def normalize_text(s: str) -> str:
    if not s: return ""
    # Lowercase, collapse whitespace, strip punctuation noise, remove accents? Keep simple
    t = re.sub(r"\s+", " ", s.strip().lower())
    # Remove leading "the " for dedup stability
    t = re.sub(r"^the\s+", "", t)
    # Remove extra punctuation for title matching
    t = re.sub(r"[!?.:;]+$", "", t)
    return t

def canonical_url(url: str) -> str:
    if not url: return ""
    url = url.strip()
    try:
        p = urlparse(url.lower())
        # Remove tracking params (utm_*, fbclid, gclid, etc.)
        qs = parse_qs(p.query)
        filtered = {k: v for k, v in qs.items() if not k.startswith("utm_") and k not in ("fbclid", "gclid", "mc_cid", "mc_eid")}
        query = urlencode(filtered, doseq=True) if filtered else ""
        # Remove fragment, sort query, lower path
        # Lowercase netloc + path (paths are case-insensitive for most scholarship sites)
        netloc = p.netloc.replace("www.", "")
        path = p.path.rstrip("/").lower()
        # Rebuild without default ports
        return urlunparse((p.scheme.lower(), netloc, path, "", query, ""))
    except:
        return url.lower().rstrip("/")

def extract_intake_year(opportunity: dict) -> int | None:
    """Derive intake/academic year from deadline or opening_date for dedup."""
    import re
    from dateutil import parser as dparser
    for field in ("deadline", "opening_date", "target_start_date"):
        val = opportunity.get(field)
        if not val: continue
        try:
            dt = dparser.parse(str(val))
            # Intake year is the year of deadline/opening; if deadline in past but intake next year, keep as is
            return dt.year
        except:
            pass
    # Fallback: search title for 4-digit year 2025-2030
    title = opportunity.get("title") or ""
    m = re.search(r"\b(202[5-9]|2030)\b", title)
    if m: return int(m.group(1))
    return None

def dedup_hash(title: str, funder: str, intake_year: int | str | None, url: str) -> str:
    """Hash normalised title + funder + intake year + canonical URL. Deadline is NOT in hash."""
    intake_str = str(intake_year or "")
    key = "|".join([
        normalize_text(title),
        normalize_text(funder or ""),
        intake_str,
        canonical_url(url or "")
    ])
    return hashlib.sha256(key.encode()).hexdigest()[:20]

def content_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode()).hexdigest()[:16]
