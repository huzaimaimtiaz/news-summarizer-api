"""
Selenium automation for Ars Technica.

Drives a real headless Chrome browser (via chromedriver) to run a keyword
search on the news site, open the first search result, and pull the
article text out of the page.

Search strategy, in order:
  1. The site's own search page.
  2. The site's WordPress ?s= search.
  3. A site-restricted web search, used only if the on-site search
     returns nothing usable.
"""

import re
import time
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

# An Ars article path looks like /<section>/<year>/<month>/<slug>/
ARTICLE_RE = re.compile(
    r"^https?://(?:www\.)?arstechnica\.com/[^/]+/\d{4}/\d{2}/[^/?#]+/?(?:[?#].*)?$",
    re.IGNORECASE,
)

# Looser fallback: a deep arstechnica.com path that isn't site furniture.
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

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def search_urls(keyword):
    """Search pages to try, in priority order."""
    q = quote_plus(keyword)
    return [
        f"{BASE}/search/?q={q}",
        f"{BASE}/?s={q}",
        f"https://html.duckduckgo.com/html/?q=site%3A{SITE_DOMAIN}+{q}",
    ]


def build_driver(timeout=45):
    """Start a headless Chrome suitable for running inside a container."""
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--blink-settings=imagesEnabled=false")
    options.add_argument("--lang=en-US")
    options.add_argument(f"--user-agent={USER_AGENT}")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])

    driver = webdriver.Chrome(service=Service("/usr/local/bin/chromedriver"),
                              options=options)
    driver.set_page_load_timeout(timeout)
    return driver


def _normalize(href):
    """
    Unwrap search-engine redirect links so the real target URL is matched.
    DuckDuckGo wraps results as /l/?uddg=<url-encoded target>.
    """
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


def find_first_result(driver, keyword):
    """Search the site and return (url, link_text) of the first article."""
    for url in search_urls(keyword):
        try:
            driver.get(url)
        except Exception:
            continue

        try:
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.TAG_NAME, "a"))
            )
        except Exception:
            pass

        _dismiss_overlays(driver)
        # Let client-rendered results settle.
        time.sleep(2.0)

        links = _candidate_links(driver)
        if links:
            return links[0]

    return None, None


def extract_article(driver, url):
    """Open an article and return (title, body_text)."""
    driver.get(url)
    try:
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.TAG_NAME, "p"))
        )
    except Exception:
        pass
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

    # Prefer paragraphs inside the article body, fall back to every <p>.
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
    """
    Diagnostic helper: report what the browser actually sees on each search
    page, so a markup change can be identified in one request.
    """
    driver = build_driver()
    report = []
    try:
        for url in search_urls(keyword):
            entry = {"search_url": url}
            try:
                driver.get(url)
                WebDriverWait(driver, 20).until(
                    EC.presence_of_element_located((By.TAG_NAME, "a"))
                )
            except Exception as exc:
                entry["load_error"] = str(exc)[:300]
            _dismiss_overlays(driver)
            time.sleep(2.0)
            try:
                entry["page_title"] = driver.title
                anchors = driver.find_elements(By.TAG_NAME, "a")
                entry["anchor_count"] = len(anchors)
                entry["candidates"] = [
                    {"url": h, "text": t[:90]}
                    for h, t in _candidate_links(driver)[:limit]
                ]
                sample = []
                for a in anchors[:250]:
                    try:
                        href = _normalize(a.get_attribute("href") or "")
                    except Exception:
                        continue
                    if SITE_DOMAIN in href:
                        sample.append(href)
                entry["sample_site_hrefs"] = sample[:limit]
            except Exception as exc:
                entry["parse_error"] = str(exc)[:300]
            report.append(entry)
        return report
    finally:
        try:
            driver.quit()
        except Exception:
            pass


def scrape(keyword):
    """
    Full flow: search -> first result -> article text.

    Returns a dict with url, title and text. Raises RuntimeError when the
    search produced no usable article.
    """
    driver = build_driver()
    try:
        url, link_text = find_first_result(driver, keyword)
        if not url:
            raise RuntimeError(
                f"No search result found on {NEWS_SOURCE} for '{keyword}'"
            )
        title, text = extract_article(driver, url)
        if not title and link_text:
            title = link_text
        return {"url": url, "title": title, "text": text}
    finally:
        try:
            driver.quit()
        except Exception:
            pass
