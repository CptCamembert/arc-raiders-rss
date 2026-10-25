#!/usr/bin/env python3
"""Maintain an image-enabled RSS feed using ARC Raiders Community Hub news."""
from __future__ import annotations

import argparse
import html
import json
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime, parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup, Tag
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

SOURCE = "https://arcraiderscommunity.com/news/"
FEED_URL = "https://cptcamembert.github.io/arc-raiders-rss/feed.xml"
MEDIA_NS = "http://search.yahoo.com/mrss/"
CONTENT_NS = "http://purl.org/rss/1.0/modules/content/"
MAX_ITEMS = 100
ET.register_namespace("media", MEDIA_NS)
ET.register_namespace("content", CONTENT_NS)
LOG = logging.getLogger(__name__)

@dataclass(frozen=True)
class Article:
    url: str
    title: str
    published: datetime
    summary: str = ""
    image: str = ""


def session_factory() -> requests.Session:
    session = requests.Session()
    retry = Retry(total=2, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update({"User-Agent": "ArcRaidersCommunityRSS/1.0 (personal RSS reader)",
                            "Accept": "text/html,application/xhtml+xml"})
    return session


def fetch_html(session: requests.Session, url: str) -> BeautifulSoup:
    result = session.get(url, timeout=20)
    result.raise_for_status()
    return BeautifulSoup(result.text, "html.parser")


def canonical_url(value: str, base: str = SOURCE) -> str:
    url = urljoin(base, html.unescape(value).strip())
    p = urlsplit(url)
    if p.scheme not in ("http", "https") or not p.netloc:
        return ""
    path = p.path.rstrip("/") or "/"
    return urlunsplit(("https", p.netloc.lower(), path, "", ""))


def article_url(href: str) -> str:
    url = canonical_url(href)
    p = urlsplit(url)
    host = p.netloc.removeprefix("www.")
    if host == "arcraiders.com":
        if not re.fullmatch(r"/(?:de/)?news/[^/]+", p.path):
            return ""
        return "https://arcraiders.com/news/" + p.path.split("/")[-1]
    if host in ("store.steampowered.com", "steamcommunity.com", "steamstore-a.akamaihd.net"):
        return url if ("news" in p.path or "announcements" in p.path) else ""
    if host == "arcraiderscommunity.com" and p.path not in ("/", "/news"):
        if any(p.path.startswith(prefix) for prefix in (
            "/wiki", "/map", "/privacy", "/support", "/looking-for-group",
            "/cdn-cgi", "/contact", "/about", "/terms", "/wp-content", "/img",
        )):
            return ""
        return url
    return ""


def image_url(value: str, base: str = SOURCE) -> str:
    if not value or value.startswith(("data:", "blob:")):
        return ""
    candidate = urljoin(base, html.unescape(value.split(" ")[0].strip()))
    parsed = urlsplit(candidate)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return ""
    if parsed.path.lower().endswith(("/bg.jpg", "/arc-raiders-social.png")):
        return ""
    return urlunsplit(("https", parsed.netloc.lower(), parsed.path, parsed.query, ""))


def get_image(node: Tag | BeautifulSoup, base: str = SOURCE) -> str:
    for tag in node.select("img, source"):
        for key in ("data-src", "data-original", "data-lazy-src", "src", "data-srcset", "srcset"):
            value = tag.get(key)
            if value:
                first = str(value).split(",")[0].strip() if "srcset" in key else str(value)
                url = image_url(first, base)
                if url:
                    return url
    for tag in [node, *node.select("[style]")]:
        style = tag.get("style", "")
        match = re.search(r"url\(['\"]?([^'\")]+)", str(style))
        if match:
            url = image_url(match.group(1), base)
            if url:
                return url
    return ""


def date_from_text(value: str, now: datetime | None = None) -> datetime | None:
    now = now or datetime.now(timezone.utc)
    value = value.strip()
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
    except ValueError:
        pass
    try:
        d = parsedate_to_datetime(value)
        return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
    except (TypeError, ValueError, IndexError):
        pass
    m = re.search(r"\b(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+(\d{4})", value, re.I)
    if m:
        month = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
                 "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}[m[2][:3].lower()]
        return datetime(int(m[3]), month, int(m[1]), 12, tzinfo=timezone.utc)
    m = re.search(r"\b(\d+)\s+(minute|hour|day|week)s? ago\b", value, re.I)
    if m:
        return now - timedelta(**{m[2].lower() + "s": int(m[1])})
    return None


def card_container(link: Tag) -> Tag:
    """Keep metadata inside one card, never a grid of neighbouring articles."""
    enclosing = link.find_parent(["article", "li"])
    if enclosing and len(enclosing.find_all(re.compile(r"^h[2-5]$"))) == 1:
        return enclosing
    if link.find(re.compile(r"^h[2-5]$")):
        return link
    node = link
    for _ in range(5):
        if not isinstance(node.parent, Tag):
            break
        node = node.parent
        if node.name in ("main", "body", "section", "nav", "footer"):
            break
        headings = node.find_all(re.compile(r"^h[2-5]$"))
        if len(headings) > 1:
            break
        if headings:
            return node
    return link


def card_title(link: Tag, card: Tag) -> str:
    heading = link.find(re.compile(r"^h[2-5]$")) or card.find(re.compile(r"^h[3-5]$"))
    title = " ".join((heading or link).stripped_strings)
    title = re.sub(r"\s+", " ", title).strip()
    return title[:250]


def read_card(link: Tag, now: datetime) -> Article | None:
    url = article_url(str(link.get("href", "")))
    if not url:
        return None
    card = card_container(link)
    heading = card.find(re.compile(r"^h[2-5]$"))
    if heading is None:
        return None
    # A sibling link in an excerpt is not the card's article destination.
    primary_link = heading.find("a", href=True) or card.find("a", href=True)
    if card is not link and primary_link is not link:
        return None
    title = card_title(link, card)
    if not title or len(title) < 8 or title.lower().startswith(("all articles", "read more", "read article", "arcraiders.com")):
        return None
    summary = ""
    para = card.find("p")
    if para:
        summary = " ".join(para.stripped_strings)[:700]
    time_tag = card.find("time")
    date = None
    if time_tag:
        date = date_from_text(str(time_tag.get("datetime", "")), now) or date_from_text(time_tag.get_text(" ", strip=True), now)
    if not date:
        date = date_from_text(card.get_text(" ", strip=True), now)
    image = get_image(card)
    return Article(url, title, date or now, summary, image)


def listing_articles(soup: BeautifulSoup, now: datetime | None = None) -> list[Article]:
    now = now or datetime.now(timezone.utc)
    main = soup.find("main")
    if main is None:
        return []
    # Keep only links inside the two news sections, excluding navigation/footer.
    headings = [h for h in main.find_all("h2") if
                any(s in h.get_text(" ", strip=True).lower() for s in ("from embark", "community transmissions"))]
    candidates = [a for a in main.select("a[href]")
                  if not a.find_parent(["nav", "footer", "aside"])]
    if not headings:
        # Some versions use a different section title. Article-shaped cards are a safe fallback.
        anchors = [a for a in candidates
                   if a.find(re.compile(r"^h[2-5]$"))
                   or (a.find_parent("article") and a.find_parent("article").find(re.compile(r"^h[2-5]$")))]
    else:
        anchors = []
        for heading in headings:
            section = heading.find_parent("section")
            anchors.extend(a for a in candidates
                           if a.find_previous("h2") is heading
                           and (section is None or a.find_parent("section") is section))
    output = {}
    for a in anchors:
        item = read_card(a, now)
        if item and item.url not in output:
            output[item.url] = item
    return list(output.values())


def article_metadata(session: requests.Session, url: str) -> tuple[str, str, datetime | None]:
    soup = fetch_html(session, url)
    summary = ""
    image = ""
    for selector in ("meta[property='og:image']", "meta[name='twitter:image']", "meta[property='twitter:image']"):
        tag = soup.select_one(selector)
        if tag and tag.get("content"):
            image = image_url(str(tag["content"]), url)
            if image:
                break
    if not image:
        article = soup.find("article") or soup.select_one(".payload-richtext") or soup.find("main")
        if article is not None:
            image = get_image(article, url)
    for selector in ("meta[property='og:description']", "meta[name='description']"):
        tag = soup.select_one(selector)
        if tag:
            summary = str(tag.get("content", ""))[:700]
            if summary:
                break
    published = None
    for selector in ("meta[property='article:published_time']", "meta[name='date']", "time[datetime]"):
        tag = soup.select_one(selector)
        if tag:
            published = date_from_text(str(tag.get("content") or tag.get("datetime") or ""))
            if published:
                break
    if not published:
        for tag in soup.select('script[type="application/ld+json"]'):
            try:
                data = json.loads(tag.string or tag.get_text())
                nodes = data if isinstance(data, list) else [data]
                for node in nodes:
                    if isinstance(node, dict):
                        published = date_from_text(str(node.get("datePublished", "")))
                        if published:
                            break
            except (ValueError, TypeError):
                pass
            if published:
                break
    return summary, image, published


def old_articles(path: Path) -> list[Article]:
    if not path.exists():
        return []
    root = ET.parse(path).getroot()
    if root.tag != "rss":
        raise ValueError("Existing file is not RSS: " + str(path))
    articles = []
    for item in root.findall("./channel/item"):
        url = (item.findtext("guid") or item.findtext("link") or "").strip()
        title = item.findtext("title") or ""
        date = date_from_text(item.findtext("pubDate") or "")
        if not (url and title and date):
            continue
        image_tag = item.find("{%s}content" % MEDIA_NS)
        image = image_tag.get("url", "") if image_tag is not None else ""
        summary = item.findtext("description") or ""
        if "<" in summary:
            summary = BeautifulSoup(summary, "html.parser").get_text(" ", strip=True)
        articles.append(Article(article_url(url) or canonical_url(url), title, date, summary, image))
    return articles


def render(articles: list[Article]) -> ET.ElementTree:
    root = ET.Element("rss", {"version": "2.0"})
    ch = ET.SubElement(root, "channel")
    for key, value in (("title", "ARC Raiders News"), ("link", SOURCE),
                       ("description", "Offizielle ARC Raiders News, Steam-Updates und Community-Berichte mit Bildern."),
                       ("language", "en"), ("ttl", "30")):
        ET.SubElement(ch, key).text = value
    ET.SubElement(ch, "lastBuildDate").text = format_datetime(datetime.now(timezone.utc), usegmt=True)
    for a in articles:
        item = ET.SubElement(ch, "item")
        ET.SubElement(item, "title").text = a.title
        ET.SubElement(item, "link").text = a.url
        ET.SubElement(item, "guid", {"isPermaLink": "true"}).text = a.url
        ET.SubElement(item, "pubDate").text = format_datetime(a.published, usegmt=True)
        if a.image:
            body = '<p><img src="%s" alt="" /></p>' % html.escape(a.image, quote=True)
            if a.summary:
                body += "<p>%s</p>" % html.escape(a.summary)
            ET.SubElement(item, "description").text = body
        else:
            ET.SubElement(item, "description").text = a.summary
        if a.image:
            ET.SubElement(item, "{%s}content" % MEDIA_NS, {"url": a.image, "medium": "image"})
            ET.SubElement(item, "{%s}encoded" % CONTENT_NS).text = body
    ET.indent(root, space="  ")
    return ET.ElementTree(root)


def update(path: Path, session: requests.Session | None = None) -> tuple[int, int]:
    old = old_articles(path)
    entries = {a.url: replace(a, image=image_url(a.image))
               for a in old if article_url(a.url)}
    session = session or session_factory()
    discovered = listing_articles(fetch_html(session, SOURCE))
    if not discovered:
        raise RuntimeError("No news cards found on the community site; refusing to alter RSS")
    # Old parser versions copied the first grid image onto unrelated articles.
    # Keep that artwork only on the cards that actually own it.
    owners: dict[str, set[str]] = {}
    for card in discovered:
        if card.image:
            owners.setdefault(card.image, set()).add(card.url)
    entries = {url: replace(a, image="")
               if a.image in owners and url not in owners[a.image] else a
               for url, a in entries.items()}
    added = 0
    for card in discovered:
        prior = entries.get(card.url)
        if prior:
            entries[card.url] = replace(prior, title=card.title,
                                        summary=card.summary or prior.summary,
                                        image=card.image or prior.image)
        else:
            entries[card.url] = card
            added += 1
    # Enrich missing thumbnails from the original article page.
    # Limit to avoid overloading the linked websites.
    to_enrich = [a for a in sorted(entries.values(), key=lambda x: x.published, reverse=True)
                 if not a.image][:25]
    for a in to_enrich:
        try:
            summary, image, publication = article_metadata(session, a.url)
        except (requests.RequestException, ValueError) as exc:
            LOG.warning("Could not read metadata for %s: %s", a.url, exc)
            continue
        if image or (summary and not a.summary):
            entries[a.url] = replace(a, summary=a.summary or summary, image=a.image or image)
    ordered = sorted(entries.values(), key=lambda x: (x.published, x.url), reverse=True)[:MAX_ITEMS]
    title_current = path.exists() and ET.parse(path).findtext('./channel/title') == 'ARC Raiders News'
    if ordered == old and title_current:
        LOG.info("No changes; existing RSS retained (%d articles)", len(old))
        return 0, len(old)
    if not ordered:
        raise RuntimeError("Refusing to write empty RSS")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    render(ordered).write(temp, encoding="utf-8", xml_declaration=True)
    temp.replace(path)
    LOG.info("Added %d articles; RSS now has %d", added, len(ordered))
    return added, len(ordered)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("feed.xml"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print("Added %d articles; %d total" % update(args.output))


if __name__ == "__main__":
    main()
