"""Legitimacy verification — VERIFIED / UNVERIFIED / SUSPICIOUS

SUSPICIOUS only for:
- payments to individuals/agents (personal email/WhatsApp for payment, not application)
- Western Union / MoneyGram / crypto / gift cards / WhatsApp payment requests
- "fee to secure/release award", "guaranteed scholarship" fee traps
Official application fees on official domain are NOT SUSPICIOUS — they go to cost_breakdown.
"""
import re
import tldextract
from urllib.parse import urlparse

# Exact registered domain allowlist (match via registered domain, not substring)
TRUSTED_REGISTERED_DOMAINS = {
    "chevening.org",
    "cscuk.fcdo.gov.uk",
    "daad.de",
    "europa.eu",
    "fulbrightonline.org",
    "gatescambridge.org",
    "rhodeshouse.ox.ac.uk",
    "mastercardfdn.org",
    "rotary.org",
    "akdn.org",
    "wellcome.org",
    "tetfund.gov.ng",
    "si.se",
    "admin.ch",
    "dfat.gov.au",
    "mext.go.jp",
    "campuschina.org",
    "studyinkorea.go.kr",
    "findaphd.com",
    "findamasters.com",
    "scholarshipportal.com",
    "scholars4dev.com",
    "opportunitydesk.org",
    "afterschoolafrica.com",
    "feps.org",
    "physiology.org",
    "physoc.org",
    "iups.org",
    "ox.ac.uk",
    "cam.ac.uk",
    "ucl.ac.uk",
    "lmu.de",
    "ki.se",
    "utoronto.ca",
    "liverpool.ac.uk",
    "manchester.ac.uk",
    "ed.ac.uk",
    "kcl.ac.uk",
}

# Known brand names that, if appearing in a non-allowlisted domain, should be flagged
BRAND_KEYWORDS = ["chevening", "daad", "rhodes", "gatescambridge", "fulbright", "erasmus", "commonwealth", "tetfund", "wellcome"]

SUSPICIOUS_PAYMENT_PATTERNS = [
    r"pay.*to.*individual|pay.*to.*agent",
    r"western union|moneygram",
    r"gift\s*card|steam\s*card|itunes\s*card",
    r"crypto|bitcoin|usdt|ethereum.*payment",
    r"whatsapp.*pay|pay.*via.*whatsapp|send.*money.*whatsapp",
    r"fee to secure|fee to release|pay.*to.*secure.*award|pay.*to.*claim",
    r"processing fee.*individual|application fee.*personal\s*account",
]

OFFICIAL_FEE_PATTERNS = [
    r"application fee.*\$?\d+.*university|application fee.*£\d+.*official",
]
# We treat official fees as cost, not suspicious — only suspicious if paired with individual/agent target

def registered_domain(url: str) -> str:
    if not url: return ""
    try:
        ext = tldextract.extract(url.lower())
        if ext.domain and ext.suffix:
            return f"{ext.domain}.{ext.suffix}"
        return urlparse(url).netloc.lower().replace("www.", "")
    except:
        return ""

def domain_is_trusted(url: str) -> bool:
    reg = registered_domain(url)
    if not reg: return False
    # Exact registered domain match, or subdomain of allowlisted (e.g., www.chevening.org)
    if reg in TRUSTED_REGISTERED_DOMAINS:
        return True
    # Also allow subdomains: check full netloc ends with trusted
    netloc = urlparse(url.lower()).netloc.replace("www.", "")
    for trusted in TRUSTED_REGISTERED_DOMAINS:
        if netloc == trusted or netloc.endswith("." + trusted):
            return True
    return False

def is_brand_impersonation(url: str) -> bool:
    reg = registered_domain(url)
    if not reg: return False
    if domain_is_trusted(url):
        return False
    low = reg.lower()
    for brand in BRAND_KEYWORDS:
        if brand in low:
            return True
    return False

def extract_official_fee(text: str):
    """Return amount string if official fee mentioned, else None."""
    if not text: return None
    m = re.search(r"application fee[^.]*?(\$|£|€)?\s*\d+[.,]?\d*", text.lower())
    return m.group(0)[:80] if m else None

def verify(opportunity: dict, source_url: str, html_text: str = "") -> tuple[str, list]:
    reasons = []
    text = ((opportunity.get("eligibility") or "") + " " + (html_text or "")).lower()
    official_link = opportunity.get("official_link") or source_url or ""
    trust = "UNVERIFIED"

    # 1. Trusted domain exact match
    if not official_link:
        reasons.append("No official link provided — verify on funder site")
    elif domain_is_trusted(official_link):
        reg = registered_domain(official_link)
        reasons.append(f"Official link on trusted domain: {reg}")
        trust = "VERIFIED"
    else:
        reg = registered_domain(official_link)
        reasons.append(f"Official link domain not in allowlist: {reg or official_link} — confirm on official site")

    # Brand impersonation flag (not auto SUSPICIOUS, but strong UNVERIFIED + warning)
    if is_brand_impersonation(official_link):
        reasons.append(f"Flag: domain contains known brand but not allowlisted: {official_link} — possible lookalike")
        # Don't auto SUSPICIOUS, but ensure not VERIFIED
        if trust == "VERIFIED":
            trust = "UNVERIFIED"

    # 2. SUSPICIOUS only for individual/agent payments, WU/MG/crypto/gift/WhatsApp, fee to secure
    for pat in SUSPICIOUS_PAYMENT_PATTERNS:
        if re.search(pat, text):
            reasons.append(f"SUSPICIOUS payment pattern: {pat}")
            return "SUSPICIOUS", reasons

    # Personal email + payment combo is suspicious; personal email alone is just UNVERIFIED
    if re.search(r"@gmail\.com|@yahoo\.com", text) and re.search(r"pay|fee|money|account.*number", text):
        reasons.append("Uses personal email with payment request — SUSPICIOUS")
        return "SUSPICIOUS", reasons
    elif re.search(r"@gmail\.com|@yahoo\.com.*apply", text):
        reasons.append("Uses personal email for applications — verify official domain")
        if trust == "VERIFIED":
            trust = "UNVERIFIED"

    # Official application fee on trusted domain → cost_breakdown, not SUSPICIOUS
    fee_snippet = extract_official_fee(text)
    if fee_snippet:
        if domain_is_trusted(official_link):
            reasons.append(f"Official application fee noted (added to cost breakdown): {fee_snippet}")
        else:
            reasons.append(f"Mentions application fee: {fee_snippet} — confirm on official site before paying")

    # 3. Deadline / funder checks (deadline missing no longer makes UNVERIFIED automatically downgrade VERIFIED? Keep as is but mark rolling)
    if not opportunity.get("deadline") and opportunity.get("deadline_status") not in ("rolling", "unknown"):
        reasons.append("No deadline found — may be rolling/unknown; confirm on official site")
    if not opportunity.get("funder"):
        reasons.append("Funder not clearly stated")

    if source_url and "findaphd" in source_url and official_link and official_link != source_url:
        reasons.append("Aggregators — confirm details on official link")

    if trust == "UNVERIFIED" and not any("Official link" in r for r in reasons):
        reasons.insert(0, "Unverified: confirm on official site before acting")

    return trust, reasons
