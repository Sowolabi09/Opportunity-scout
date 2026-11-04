"""Telegram alerts — free Bot API."""
import os, requests

BOT_TOKEN=os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID=os.getenv("TELEGRAM_CHAT_ID")

def _can_send(): return bool(BOT_TOKEN and CHAT_ID)

def send_telegram(text: str, chat_id: str = None) -> bool:
    if not _can_send():
        print("[telegram] BOT_TOKEN/CHAT_ID not set — skipping")
        return False
    cid=chat_id or CHAT_ID
    url=f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload={"chat_id": cid, "text": text, "parse_mode": "Markdown", "disable_web_page_preview": False}
    try:
        r=requests.post(url, json=payload, timeout=10)
        if r.status_code==429:
            print(f"[telegram] 429 rate limited: {r.text}")
            return False
        r.raise_for_status()
        print(f"[telegram] sent → {cid}")
        return True
    except Exception as e:
        print(f"[telegram] failed: {e}")
        return False

def strong_match_message(opp: dict) -> str:
    return (
        f"🎓 *Strong match* — Score {opp.get('match_score')}/100\n"
        f"*{opp.get('title','Opportunity')}*\n"
        f"Funder: {opp.get('funder','')} | {opp.get('country','')} | {opp.get('level','')} | {opp.get('funding_type','')} funded\n"
        f"Deadline: {opp.get('deadline','TBD')} | Trust: {opp.get('trust_label','UNVERIFIED')}\n"
        f"Why: {opp.get('match_reasons','')[:200]}\n"
        f"[View official page]({opp.get('official_link','#')})\n\n"
        f"_Full card sent to your email._"
    )

def digest_message(opps: list, title="Possible matches digest") -> str:
    if not opps: return ""
    lines=[f"📋 *{title}* — {len(opps)} items\n"]
    for o in opps[:10]:
        lines.append(f"• {o.get('title','')} — {o.get('country','')} — Closes {str(o.get('deadline','TBD'))[:10]} — Score {o.get('match_score','?')} — [link]({o.get('official_link','#')})")
    if len(opps)>10: lines.append(f"\n_…and {len(opps)-10} more in dashboard_")
    return "\n".join(lines)

def system_alert_message(text: str) -> str:
    return f"⚠️ *Opportunity Scout system alert*\n{text[:3500]}"
