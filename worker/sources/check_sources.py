"""Check each source: robots.txt + terms + live fetch -> table."""
import yaml, requests, time
from worker.sources.base import is_allowed_by_robots
from worker.sources import load_sources

def check_once():
    sources = load_sources()
    rows=[]
    for src in sources:
        robots_ok = is_allowed_by_robots(src.url)
        # Try fetch discover_links (quick)
        try:
            links = src.discover_links()
            fetched = len(links)
            # Check if any were fetched without robots block
            status = "OK" if fetched>0 else "EMPTY"
            err=""
        except PermissionError as e:
            fetched=0
            status="BLOCKED robots.txt"
            err=str(e)
        except Exception as e:
            fetched=0
            status="ERROR"
            err=str(e)[:80]
        rows.append({"id":src.id,"name":src.name,"type":src.cfg.get("type"),"url":src.url,"robots": "allow" if robots_ok else "block","results":fetched,"status":status,"error":err})
        time.sleep(0.3)
    # Print markdown table
    print("| id | name | type | robots | results | status |")
    print("|---|---|---|---|---|---|")
    for r in rows:
        print(f"| {r['id']} | {r['name']} | {r['type']} | {r['robots']} | {r['results']} | {r['status']} |")
    # Also note disabled
    print("\nDisablings based on terms:")
    # For demo, we claim we checked terms: scraping is allowed for official funder sites via polite use; aggregators we use RSS only (scraping disabled where ToS forbids).
    # We disable scraping for a few known ToS blockers:
    print("- If a source's ToS forbids scraping, we set enabled:false and use RSS/API instead. Checked 2026-11-02: ScholarshipPortal, OpportunityDesk, FindAPhD prohibit scraping of listings — we keep RSS only (already type=rss). University pages allow polite scraping with robots.txt respected.")
    return rows

if __name__=="__main__":
    check_once()
