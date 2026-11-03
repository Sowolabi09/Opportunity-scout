from .base import BaseSource

class RSSSource(BaseSource):
    """Generic RSS — each entry is a candidate opportunity page."""
    def discover_links(self):
        entries=self.fetch_rss()
        links=[]
        for e in entries:
            links.append({"title": e["title"], "url": e["link"], "summary": e.get("summary","")})
        return links

class ScrapeSource(BaseSource):
    """Generic scrape — fetch index page and extract links to detail pages."""
    def discover_links(self):
        # Fallback: the index URL itself is the candidate
        # Specific sources can override to crawl listing links
        html=""
        try:
            html=self.fetch(self.url)
        except Exception as e:
            print(f"[{self.id}] fetch failed: {e}")
            return []
        from bs4 import BeautifulSoup
        soup=BeautifulSoup(html,"lxml")
        links=[]
        for a in soup.find_all("a", href=True)[:50]:
            href=a["href"]
            if href.startswith("/"):  # relative
                from urllib.parse import urljoin
                href=urljoin(self.url, href)
            if href.startswith("http"):
                title=a.get_text(strip=True)
                if len(title)>10:
                    links.append({"title": title, "url": href})
        # dedup by url
        seen=set(); out=[]
        for l in links:
            if l["url"] not in seen:
                seen.add(l["url"]); out.append(l)
        # If no links found, treat index as candidate
        if not out:
            out=[{"title": self.name, "url": self.url}]
        return out[:30]
