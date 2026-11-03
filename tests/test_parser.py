"""Test that sources can discover links without crashing (no network — mocked)."""
from unittest.mock import patch, MagicMock
from worker.sources.rss_source import ScrapeSource

def test_scrape_discovers_links():
    html='<html><body><a href="/scholarship-a">DAAD Scholarship for Physiology MSc</a><a href="https://example.com/b">Short</a></body></html>'
    cfg={"id":"test","name":"Test","url":"https://example.com","type":"scrape"}
    s=ScrapeSource(cfg)
    with patch.object(s, "fetch", return_value=html):
        links=s.discover_links()
        assert len(links)>=1
        assert any("daad" in l["title"].lower() for l in links)
