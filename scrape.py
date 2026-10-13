#!/usr/bin/env python3
"""Turn lexpress.mu article cards into an RSS 2.0 feed.

Standard library only (no pip install). Exits with an error if it finds
zero articles or can't fetch the page, so GitHub Actions emails you.

Usage:
    python scrape.py                  # fetch live pages, write docs/lexpress.xml
    python scrape.py --file page.html # parse a saved HTML file instead (testing)
"""
import email.utils
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin

SITE = "https://lexpress.mu"
# Pages to scan. Add section pages here if you want more articles covered.
PAGES = [SITE + "/"]
OUTPUT = "docs/lexpress.xml"
MAX_ITEMS = 100
MIN_EXPECTED = 3  # fewer cards than this = the layout probably changed

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)


class CardParser(HTMLParser):
    """Finds <a href="/s/..."> blocks containing an <h3> (title) and <h4> (category)."""

    def __init__(self):
        super().__init__()
        self.cards = []
        self.cur = None
        self.field = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a" and (a.get("href") or "").startswith("/s/"):
            self.cur = {"href": a["href"], "title": "", "cat": "", "img": ""}
        elif self.cur is not None:
            if tag == "img" and not self.cur["img"]:
                self.cur["img"] = a.get("src", "")
            elif tag in ("h3", "h4"):
                self.field = tag

    def handle_data(self, data):
        if self.cur is None:
            return
        if self.field == "h3":
            self.cur["title"] += data
        elif self.field == "h4":
            self.cur["cat"] += data

    def handle_endtag(self, tag):
        if tag in ("h3", "h4"):
            self.field = None
        elif tag == "a" and self.cur is not None:
            if self.cur["title"].strip():
                self.cards.append(self.cur)
            self.cur = None


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "fr"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def article_id(link):
    m = re.search(r"-(\d+)$", link.rstrip("/"))
    return int(m.group(1)) if m else 0


def load_existing():
    """Read the previous feed so items keep their first-seen date and
    don't vanish when they scroll off the homepage."""
    items = {}
    if not os.path.exists(OUTPUT):
        return items
    try:
        for it in ET.parse(OUTPUT).getroot().iter("item"):
            link = it.findtext("link")
            if link:
                items[link] = {
                    "title": it.findtext("title") or "",
                    "cat": it.findtext("category") or "",
                    "img": (re.search(r'src="([^"]+)"', it.findtext("description") or "") or [None, ""])[1],
                    "pub": it.findtext("pubDate") or "",
                }
    except ET.ParseError:
        pass  # corrupt old file: start fresh
    return items


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--file":
        pages_html = [open(sys.argv[2], encoding="utf-8").read()]
    else:
        pages_html = [fetch(u) for u in PAGES]

    found = {}
    for html in pages_html:
        p = CardParser()
        p.feed(html)
        for c in p.cards:
            link = urljoin(SITE, c["href"])
            found[link] = {
                "title": " ".join(c["title"].split()),
                "cat": " ".join(c["cat"].split()),
                "img": urljoin(SITE, c["img"]) if c["img"] else "",
            }

    if len(found) < MIN_EXPECTED:
        sys.exit(f"ERROR: only {len(found)} articles found - lexpress.mu layout may have changed.")

    now = email.utils.format_datetime(datetime.now(timezone.utc))
    items = load_existing()
    for link, c in found.items():
        pub = items.get(link, {}).get("pub") or now
        items[link] = {**c, "pub": pub}

    ordered = sorted(items.items(), key=lambda kv: article_id(kv[0]), reverse=True)[:MAX_ITEMS]

    rss = ET.Element("rss", version="2.0")
    ch = ET.SubElement(rss, "channel")
    ET.SubElement(ch, "title").text = "L'express (Maurice) - unofficial feed"
    ET.SubElement(ch, "link").text = SITE
    ET.SubElement(ch, "description").text = "Unofficial feed generated from lexpress.mu"
    ET.SubElement(ch, "language").text = "fr"
    ET.SubElement(ch, "lastBuildDate").text = now
    for link, c in ordered:
        it = ET.SubElement(ch, "item")
        ET.SubElement(it, "title").text = c["title"]
        ET.SubElement(it, "link").text = link
        ET.SubElement(it, "guid", isPermaLink="true").text = link
        ET.SubElement(it, "pubDate").text = c["pub"]
        if c["cat"]:
            ET.SubElement(it, "category").text = c["cat"]
        desc = f"<p>{c['cat']}</p>" if c["cat"] else ""
        if c["img"]:
            desc += f'<img src="{c["img"]}" alt="">'
        ET.SubElement(it, "description").text = desc

    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    ET.indent(rss)
    ET.ElementTree(rss).write(OUTPUT, encoding="utf-8", xml_declaration=True)
    print(f"OK: {len(found)} found on page(s), {len(ordered)} items in feed")


if __name__ == "__main__":
    main()
