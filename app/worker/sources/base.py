"""BaseSource — with robots.txt enforcement."""
import time, hashlib, requests, feedparser
from abc import ABC, abstractmethod
from bs4 import BeautifulSoup
import os
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

USER_AGENT = os.getenv("SCOUT_USER_AGENT", "OpportunityScout/1.0 (+https://github.com/YOU/opportunity-scout; contact: via GitHub)")

_robots_cache = {}

def is_allowed_by_robots(url: str, user_agent: str = USER_AGENT) -> bool:
    """Check robots.txt; cache per domain. Fail-open if robots.txt unreachable, fail-closed if disallowed."""
    try:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in _robots_cache:
            rp = RobotFileParser()
            rp.set_url(f"{origin}/robots.txt")
            try:
                rp.read()
                _robots_cache[origin] = rp
            except:
                # If robots.txt fails to fetch, allow (fail-open) but log
                _robots_cache[origin] = None
                return True
        rp = _robots_cache[origin]
        if rp is None:
            return True
        return rp.can_fetch(user_agent, url)
    except:
        return True

class BaseSource(ABC):
    def __init__(self, cfg: dict):
        self.id = cfg["id"]
        self.name = cfg["name"]
        self.cfg = cfg
        self.url = cfg.get("url")
        self.rss_url = cfg.get("rss")

    def fetch(self, url: str) -> str:
        if not is_allowed_by_robots(url):
            raise PermissionError(f"Blocked by robots.txt: {url}")
        headers={"User-Agent": USER_AGENT}
        r=requests.get(url, headers=headers, timeout=int(os.getenv("REQUEST_TIMEOUT","20")))
        r.raise_for_status()
        return r.text

    def fetch_rss(self):
        if not self.rss_url: return []
        if not is_allowed_by_robots(self.rss_url):
            print(f"[{self.id}] RSS blocked by robots.txt: {self.rss_url}")
            return []
        parsed=feedparser.parse(self.rss_url)
        items=[]
        for e in parsed.entries[:30]:
            items.append({
                "title": e.get("title",""),
                "link": e.get("link",""),
                "published": e.get("published",""),
                "summary": e.get("summary",""),
            })
        return items

    def fetch_page_text(self, url: str) -> str:
        html=self.fetch(url)
        soup=BeautifulSoup(html,"lxml")
        for tag in soup(["script","style","nav","footer"]): tag.decompose()
        return soup.get_text(" ", strip=True)[:20000]

    @abstractmethod
    def discover_links(self) -> list[dict]:
        pass

    def content_hash(self, text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()[:16]
