"""
Selenium automation for Ars Technica.

Drives a real headless Chrome browser (via chromedriver) to search the news
site, open the first result, and pull the article text out of the page.

The site fronts its HTML pages with a bot interstitial that can appear for
cloud/datacenter IPs, so the scraper is layered:

  1. The site's own search page, driven by Chrome, waiting for any
     interstitial to clear before reading results.
  2. A site-restricted web search.
  3. The site's public RSS feed, which is not behind the interstitial, used
     to locate a matching article.

Whichever layer finds the article, Chrome is then used to open that article
page and extract its text; the feed summary is only used if the article page
itself cannot be rendered.
"""

import os
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from html import unescape
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

NEWS_SOURCE = "Ars Technica"
SITE_DOMAIN = "arstechnica.com"
BASE = "https://arstechnica.com"

# Section feeds are aggregated so a keyword has a wide pool to match against.
FEED_URLS = [
    "https://feeds.arstechnica.com/arstechnica/index",
    "https://feeds.arstechnica.com/arstechnica/technology-lab",
    "https://feeds.arstechnica.com/arstechnica/information-technology",
    "https://feeds.arstechnica.com/arstechnica/gadgets",
    "https://feeds.arstechnica.com/arstechnica/science",
    "https://feeds.arstechnica.com/arstechnica/tech-policy",
    "https://feeds.arstechnica.com/arstechnica/security",
    "https://feeds.arstechnica.com/arstechnica/business",
    "https://feeds.arstechnica.com/arstechnica/gaming",
    "https://feeds.arstechnica.com/arstechnica/apple",
]

CONTENT_TAG = "{http://purl.org/rss/1.0/modules/content/}encoded"

# An Ars article path looks like /<section>/<year>/<month>/<slug>/
ARTICLE_RE = re.compile(
    r"^https?://(?:www\.)?arstechnica\.com/[^/]+/\d{4}/\d{2}/[^/?#]+/?(?:[?#].*)?$",
    re.IGNORECASE,
)

LOOSE_RE = re.compile(
    r"^https?://(?:www\.)?arstechnica\.com/([^/?#]+)/([^/?#]+)/([^/?#]+)",
    re.IGNORECASE,
)

NON_ARTICLE_SEGMENTS = {
    "search", "about-us", "contact-us", "newsletters", "subscribe", "store",
    "civis", "staff-directory", "privacy-policy", "terms-of-service", "rss",
    "feeds", "cars", "author", "tag", "topic", "page", "wp-content",
    "wp-json", "sponsored", "advertise",
}

# Titles shown by bot interstitials while they resolve.
CHALLENGE_MARKERS = (
    "just a moment", "human verification", "attention required",
    "checking your browser", "verify you are human", "ddos protection",
    "access denied", "one moment",
)

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# Kept deliberately short so a request always answers well inside a normal
# HTTP client timeout, even when every page has to be given up on.
CHALLENGE_WAIT = int(os.environ.get("CHALLENGE_WAIT_SECONDS", "10"))
ELEMENT_WAIT = int(os.environ.get("ELEMENT_WAIT_SECONDS", "8"))
FEED_TIMEOUT = int(os.environ.get("FEED_TIMEOUT_SECONDS", "12"))


def search_urls(keyword):
    """Search pages to try, in priority order."""
    q = quote_plus(keyword)
    return [
        f"{BASE}/search/?q={q}",
        f"{BASE}/?s={q}",
        f"https://html.duckduckgo.com/html/?q=site%3A{SITE_DOMAIN}+{q}",
    ]


def build_driver(timeout=60):
    """Start a headless Chrome suitable for running inside a container."""
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--lang=en-US,en")
    options.add_argument(f"--user-agent={USER_AGENT}")
    # Reduce the obvious automation fingerprints that trip bot checks.
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    driver = webdriver.Chrome(service=Service("/usr/local/bin/chromedriver"),
                              options=options)
    driver.set_page_load_timeout(timeout)
    try:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source":
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
                "Object.defineProperty(navigator,'languages',"
                "{get:()=>['en-US','en']});"
                "Object.defineProperty(navigator,'plugins',{get:()=>[1,2,3,4,5]});"},
        )
    except Exception:
        pass
    return driver


def _page_title(driver):
    try:
        return (driver.title or "").lower()
    except Exception:
        return ""


def _is_challenged(driver):
    title = _page_title(driver)
    return any(marker in title for marker in CHALLENGE_MARKERS)


def wait_past_challenge(driver, timeout=None):
    """
    Bot interstitials normally resolve on their own after a few seconds.
    Poll until the page stops looking like one, or the timeout expires.
    """
    timeout = CHALLENGE_WAIT if timeout is None else timeout
    deadline = time.time() + timeout
    reloaded = False
    while time.time() < deadline:
        if not _is_challenged(driver):
            return True
        time.sleep(2.5)
        # One reload partway through often finishes the handshake.
        if not reloaded and time.time() > deadline - timeout / 2:
            reloaded = True
            try:
                driver.refresh()
            except Exception:
                pass
    return not _is_challenged(driver)


def _normalize(href):
    """Unwrap search-engine redirect links to the real target URL."""
    if not href:
        return ""
    if "duckduckgo.com/l/" in href or href.startswith("/l/"):
        target = parse_qs(urlparse(href).query).get("uddg", [""])[0]
        if target:
            return unquote(target)
    return href


def _dismiss_overlays(driver):
    """Click away cookie/consent banners that can cover the results."""
    labels = ["Accept", "I Agree", "Agree", "Got it", "Continue", "Accept All"]
    for label in labels:
        try:
            for el in driver.find_elements(
                By.XPATH, f"//button[contains(., '{label}')]"
            )[:2]:
                if el.is_displayed():
                    el.click()
                    time.sleep(0.4)
                    return
        except Exception:
            continue


def _candidate_links(driver):
    """Collect plausible article URLs from the current results page."""
    strict, loose = [], []
    for anchor in driver.find_elements(By.TAG_NAME, "a"):
        try:
            href = _normalize(anchor.get_attribute("href") or "")
            text = (anchor.text or "").strip()
        except Exception:
            continue
        if not href:
            continue
        href = href.split("#")[0]
        if ARTICLE_RE.match(href):
            strict.append((href, text))
            continue
        match = LOOSE_RE.match(href)
        if match and match.group(1).lower() not in NON_ARTICLE_SEGMENTS:
            loose.append((href, text))

    seen, ordered = set(), []
    for href, text in strict + loose:
        key = href.rstrip("/")
        if key not in seen:
            seen.add(key)
            ordered.append((href, text))
    return ordered


# ---------------------------------------------------------------------
# RSS feed support (not behind the bot interstitial)
# ---------------------------------------------------------------------

def _http_get(url, timeout=FEED_TIMEOUT):
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def strip_html(raw):
    text = re.sub(r"<script.*?</script>", " ", raw or "", flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", unescape(text)).strip()


def feed_items():
    """
    Fetch and parse the site's RSS feeds into a de-duplicated list of
    articles. All section feeds are aggregated so keyword matching has a
    wide pool to search.
    """
    items, seen = [], set()
    for feed_url in FEED_URLS:
        try:
            root = ET.fromstring(_http_get(feed_url))
        except Exception:
            continue
        for node in root.iter("item"):
            link = (node.findtext("link") or "").strip()
            if not link:
                continue
            key = link.split("?")[0].rstrip("/")
            if key in seen:
                continue
            seen.add(key)
            body = node.findtext(CONTENT_TAG) or node.findtext("description") or ""
            items.append({
                "title": unescape((node.findtext("title") or "").strip()),
                "url": link,
                "text": strip_html(body),
            })
    return items


def match_feed_items(keyword, items=None):
    """Rank feed articles by how well they match the keyword."""
    items = items if items is not None else feed_items()
    needle = (keyword or "").lower().strip()
    words = [w for w in re.findall(r"[a-z0-9]+", needle) if len(w) > 2]

    scored = []
    for position, item in enumerate(items):
        haystack = f"{item['title']} {item['text']}".lower()
        if needle and needle in haystack:
            score = 3
        elif words and all(w in haystack for w in words):
            score = 2
        elif words and any(w in haystack for w in words):
            score = 1
        else:
            score = 0
        if score:
            scored.append((score, position, item))

    scored.sort(key=lambda row: (-row[0], row[1]))
    return [row[2] for row in scored]


# ---------------------------------------------------------------------
# Search + article extraction
# ---------------------------------------------------------------------

def find_first_result(driver, keyword):
    """Search the site and return (url, link_text) of the first article."""
    walled_hosts = set()

    for url in search_urls(keyword):
        host = urlparse(url).netloc.lower()
        # Once a host has shown its interstitial, a second page on the same
        # host will show it too, so skip it instead of waiting again.
        if host in walled_hosts:
            continue

        try:
            driver.get(url)
        except Exception:
            continue
        try:
            WebDriverWait(driver, ELEMENT_WAIT).until(
                EC.presence_of_element_located((By.TAG_NAME, "a"))
            )
        except Exception:
            pass

        # Give any bot interstitial a chance to clear itself.
        if not wait_past_challenge(driver):
            walled_hosts.add(host)
            continue

        _dismiss_overlays(driver)
        time.sleep(1.0)

        links = _candidate_links(driver)
        if links:
            return links[0]

    return None, None


def extract_article(driver, url):
    """Open an article and return (title, body_text)."""
    driver.get(url)
    try:
        WebDriverWait(driver, ELEMENT_WAIT).until(
            EC.presence_of_element_located((By.TAG_NAME, "p"))
        )
    except Exception:
        pass
    wait_past_challenge(driver)
    _dismiss_overlays(driver)

    title = ""
    for selector in ("h1", "header h1", "[data-testid='headline']"):
        try:
            el = driver.find_element(By.CSS_SELECTOR, selector)
            if el.text.strip():
                title = el.text.strip()
                break
        except Exception:
            continue
    if not title:
        title = (driver.title or "").split("|")[0].strip()

    paragraphs = []
    for selector in (
        "div.post-content p",
        "article p",
        "main p",
        "div[class*='article'] p",
        "p",
    ):
        try:
            found = driver.find_elements(By.CSS_SELECTOR, selector)
        except Exception:
            continue
        texts = []
        for p in found:
            try:
                t = (p.text or "").strip()
            except Exception:
                continue
            if len(t) < 45:
                continue
            low = t.lower()
            if any(
                junk in low
                for junk in (
                    "sign up for", "newsletter", "subscribe", "cookie",
                    "all rights reserved", "may earn compensation",
                    "advertisement", "follow us on",
                )
            ):
                continue
            texts.append(t)
        if len(texts) >= 2:
            paragraphs = texts
            break

    seen, body = set(), []
    for t in paragraphs:
        if t not in seen:
            seen.add(t)
            body.append(t)

    return title, "\n".join(body)


def debug_search(keyword, limit=15):
    """Diagnostic view of what the browser sees on each search page."""
    driver = build_driver()
    report = {"search_pages": [], "feed": {}}
    try:
        for url in search_urls(keyword):
            entry = {"search_url": url}
            try:
                driver.get(url)
                WebDriverWait(driver, ELEMENT_WAIT).until(
                    EC.presence_of_element_located((By.TAG_NAME, "a"))
                )
            except Exception as exc:
                entry["load_error"] = str(exc)[:200]
            entry["title_before_wait"] = driver.title
            entry["challenge_cleared"] = wait_past_challenge(driver)
            _dismiss_overlays(driver)
            time.sleep(1.0)
            try:
                entry["title_after_wait"] = driver.title
                anchors = driver.find_elements(By.TAG_NAME, "a")
                entry["anchor_count"] = len(anchors)
                entry["candidates"] = [
                    {"url": h, "text": t[:90]}
                    for h, t in _candidate_links(driver)[:limit]
                ]
            except Exception as exc:
                entry["parse_error"] = str(exc)[:200]
            report["search_pages"].append(entry)
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    try:
        items = feed_items()
        matches = match_feed_items(keyword, items)
        report["feed"] = {
            "items_fetched": len(items),
            "matches": len(matches),
            "first_matches": [
                {"title": m["title"][:90], "url": m["url"],
                 "text_chars": len(m["text"])}
                for m in matches[:3]
            ],
            "sample_titles": [i["title"][:70] for i in items[:5]],
        }
    except Exception as exc:
        report["feed"] = {"error": str(exc)[:200]}

    return report


def scrape(keyword):
    """
    Full flow: find the article, then scrape it with Chrome.

    Returns a dict with url, title, text and the route that found it.
    Raises RuntimeError when no article matches the keyword at all.
    """
    driver = build_driver()
    try:
        route = "site-search"
        url, link_text = find_first_result(driver, keyword)
        feed_match = None

        if not url:
            # The HTML pages are gated; locate the article via the RSS feed.
            matches = match_feed_items(keyword)
            if matches:
                feed_match = matches[0]
                url = feed_match["url"]
                link_text = feed_match["title"]
                route = "rss-feed"

        if not url:
            raise RuntimeError(
                f"No article matching '{keyword}' found on {NEWS_SOURCE}"
            )

        title, text = extract_article(driver, url)
        if not title and link_text:
            title = link_text

        # If the article page itself is gated, fall back to the feed text.
        if len(text) < 200 and feed_match and len(feed_match["text"]) > len(text):
            text = feed_match["text"]
            route += "+feed-text"

        return {"url": url, "title": title, "text": text, "route": route}
    finally:
        try:
            driver.quit()
        except Exception:
            pass
