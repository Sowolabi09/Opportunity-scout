"""Gmail SMTP emailer — uses app password (free, ~500/day)."""
import os, smtplib, ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

GMAIL_USER=os.getenv("GMAIL_USER")
GMAIL_APP_PASSWORD=os.getenv("GMAIL_APP_PASSWORD")
ALERT_FROM=os.getenv("ALERT_FROM_EMAIL") or GMAIL_USER
ALERT_TO=os.getenv("ALERT_TO_EMAIL") or GMAIL_USER

def _can_send(): return bool(GMAIL_USER and GMAIL_APP_PASSWORD)

def opportunity_card_html(opp: dict) -> str:
    costs=opp.get("cost_breakdown") or {}
    covers=opp.get("funding_covers") or {}
    def cost_rows():
        if not costs: return "<tr><td colspan=3>No cost breakdown yet — check official link</td></tr>"
        rows=""
        for k,v in costs.items():
            if isinstance(v, dict):
                rows+=f"<tr><td>{k}</td><td>{v.get('amount','?')}</td><td>{v.get('source','ESTIMATED')}</td></tr>"
            else:
                rows+=f"<tr><td>{k}</td><td>{v}</td><td>ESTIMATED</td></tr>"
        return rows
    trust_label=opp.get("trust_label","UNVERIFIED")
    trust_color={"VERIFIED":"#16a34a","UNVERIFIED":"#d97706","SUSPICIOUS":"#dc2626"}.get(trust_label,"#6b7280")
    gap_list=opp.get("gap_list") or []
    gaps_html="<ul>"+"".join(f"<li>{g}</li>" for g in gap_list)+"</ul>" if gap_list else "<p>✅ No gaps detected — you meet the stated requirements</p>"
    deadline=opp.get("deadline") or "See official link"
    return f"""
    <div style="font-family:Inter,Arial,sans-serif; max-width:680px; margin:auto; border:1px solid #e5e7eb; border-radius:12px; overflow:hidden">
      <div style="background:#0f172a; color:white; padding:20px">
        <h2 style="margin:0">{opp.get('title','Opportunity')}</h2>
        <p style="margin:6px 0 0; opacity:0.9">{opp.get('funder','')} — {opp.get('host','')} — {opp.get('country','')}</p>
        <span style="display:inline-block; margin-top:10px; background:{trust_color}; color:white; padding:4px 10px; border-radius:999px; font-size:12px; font-weight:700">{trust_label}</span>
        <span style="display:inline-block; margin-left:8px; background:white; color:#0f172a; padding:4px 10px; border-radius:999px; font-size:12px; font-weight:700">Score {opp.get('match_score','?')}/100 — {opp.get('level','')} • {opp.get('funding_type','')} funded</span>
      </div>
      <div style="padding:20px">
        <p><b>Why it matched:</b> {opp.get('match_reasons','')}</p>
        <p><b>Deadline:</b> {deadline} <span style="color:#6b7280">({opp.get('deadline_tz','')})</span></p>
        <p><b>Official link:</b> <a href="{opp.get('official_link','#')}">{opp.get('official_link','#')}</a> <span style="color:#6b7280">(found via {opp.get('source_id','')})</span></p>
        <h3>Funding</h3><p>{opp.get('funding_type','unknown')} — covers: {', '.join([k for k,v in covers.items() if v]) or 'See official link'}</p>
        <h3>Eligibility</h3><p>{opp.get('eligibility','See official link')}</p>
        <h3>Required documents</h3><p>{', '.join(opp.get('required_docs') or []) or 'See official link'}</p>
        <h3>Application steps</h3><p>{opp.get('application_steps','See official link')}</p>
        <h3>Your gaps</h3>{gaps_html}
        <h3>Cost breakdown</h3>
        <table style="width:100%; border-collapse:collapse; font-size:14px">
          <tr style="background:#f8fafc"><th style="text-align:left; border:1px solid #e5e7eb; padding:6px">Item</th><th style="border:1px solid #e5e7eb; padding:6px">Amount</th><th style="border:1px solid #e5e7eb; padding:6px">Source</th></tr>
          {cost_rows()}
        </table>
        <p style="font-size:12px; color:#6b7280">Total to start: {opp.get('cost_total_to_start','?')} • Total to complete: {opp.get('cost_total_to_complete','?')} — figures marked ESTIMATED are approximations, not official.</p>
        <p style="font-size:12px; color:#6b7280">Trust reasons: {', '.join(opp.get('trust_reasons') or [])}</p>
        <p style="font-size:12px; color:#6b7280">Found: {opp.get('created_at','')} | ID: {opp.get('id','')}</p>
        <a href="{opp.get('official_link','#')}" style="display:inline-block; background:#2563eb; color:white; padding:12px 20px; border-radius:8px; text-decoration:none; font-weight:700; margin-top:12px">View official page →</a>
      </div>
    </div>
    """

def send_email(subject: str, html_body: str, to: str = None, text_fallback: str = None) -> bool:
    if not _can_send():
        print("[email] GMAIL_USER/APP_PASSWORD not set — skipping email")
        return False
    to = to or ALERT_TO
    msg=MIMEMultipart("alternative")
    msg["From"]=ALERT_FROM
    msg["To"]=to
    msg["Subject"]=subject
    msg.attach(MIMEText(text_fallback or "View this email as HTML", "plain"))
    msg.attach(MIMEText(html_body, "html"))
    try:
        ctx=ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as s:
            s.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            s.sendmail(ALERT_FROM, [to], msg.as_string())
        print(f"[email] sent → {to} : {subject}")
        return True
    except Exception as e:
        print(f"[email] failed: {e}")
        return False

def strong_match_subject(opp: dict) -> str:
    dl = opp.get("deadline")
    # try format as YYYY-MM-DD
    try:
        if dl: dl = str(dl)[:10]
        else: dl="TBD"
    except: dl="TBD"
    return f"Closes {dl}: {opp.get('funding_type','')} {opp.get('level','')} in {opp.get('field','')}, {opp.get('country','')} — {opp.get('title','')[:60]}"

def send_strong_alert(opp: dict) -> bool:
    subject=strong_match_subject(opp)
    html=opportunity_card_html(opp)
    return send_email(subject, html)

def send_system_alert(subject: str, body: str) -> bool:
    html=f"<pre style='font-family:monospace; background:#fef2f2; padding:16px; border-radius:8px'>{body}</pre>"
    return send_email(f"[Opportunity Scout ALERT] {subject}", html)
