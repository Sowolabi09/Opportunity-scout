import re

def cheap_keyword_filter(text: str, required_any=None, blocklist=None) -> bool:
    """Return True if text passes cheap filter (no AI needed)."""
    if not text: return False
    t = text.lower()
    if blocklist and any(kw.lower() in t for kw in blocklist):
        return False
    if required_any and not any(kw.lower() in t for kw in required_any):
        return False
    return True

def extract_emails(text: str): return re.findall(r"[\w\.-]+@[\w\.-]+\.\w+", text or "")
def has_payment_request(text: str) -> bool:
    suspicious = ["pay to apply","application fee $","send money to","whatsapp us at","western union","pay via gift card","processing fee"]
    t = (text or "").lower()
    return any(p in t for p in suspicious)

PHYSIOLOGY_KEYWORDS = [
 "physiology","neuroscience","biomedical","pharmacology","public health","nutrition",
 "exercise science","medical sciences","anatomy","molecular biology","biochemistry",
 "physiotherapy","health sciences","biomedical science"
]
