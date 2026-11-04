"""Source registry loader."""
import yaml, os
from .rss_source import RSSSource, ScrapeSource

def load_sources(config_path="config/sources.yaml"):
    with open(config_path) as f:
        cfg=yaml.safe_load(f)
    sources=[]
    for s in cfg.get("sources",[]):
        if not s.get("enabled", True): continue
        t=s.get("type","scrape")
        if t=="rss":
            sources.append(RSSSource(s))
        else:
            sources.append(ScrapeSource(s))
    return sources
