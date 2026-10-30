"""
REST API server.

Exposes GET /get?keyword=<kw> on port 7000. It drives Selenium + headless
Chrome to search the assigned news source, opens the first search result,
summarizes it, and returns the result as JSON.
"""

import logging
import os

from flask import Flask, jsonify, request

from scraper import NEWS_SOURCE, scrape
from summarizer import summarize

REGISTRATION = "FA23-BDS-017"
PORT = int(os.environ.get("PORT", "7000"))
SUMMARY_SENTENCES = int(os.environ.get("SUMMARY_SENTENCES", "4"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("news-api")

app = Flask(__name__)
app.json.sort_keys = False

INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>News Summarizer API</title>
<style>
  body {{ font-family: -apple-system, "Segoe UI", Roboto, Arial, sans-serif;
         margin: 0; padding: 40px 20px; color: #1a1a1a; background: #fff; }}
  .wrap {{ max-width: 680px; margin: 0 auto; }}
  h1 {{ font-size: 26px; margin: 0 0 4px; }}
  .reg {{ font-size: 30px; font-weight: 700; letter-spacing: 1px;
          margin: 12px 0 20px; }}
  table {{ border-collapse: collapse; margin: 18px 0; }}
  td {{ padding: 5px 18px 5px 0; vertical-align: top; }}
  td.k {{ color: #555; }}
  code {{ background: #f3f3f3; padding: 2px 6px; border-radius: 3px; }}
  form {{ margin-top: 22px; }}
  input[type=text] {{ padding: 8px; width: 260px; font-size: 15px; }}
  button {{ padding: 8px 16px; font-size: 15px; cursor: pointer; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>News Search &amp; Summarization API</h1>
  <div class="reg">Registration No: {registration}</div>
  <table>
    <tr><td class="k">News source</td><td>{source}</td></tr>
    <tr><td class="k">Endpoint</td><td><code>/get?keyword=&lt;keyword&gt;</code></td></tr>
    <tr><td class="k">Method</td><td>GET</td></tr>
    <tr><td class="k">Port</td><td>{port}</td></tr>
    <tr><td class="k">Automation</td><td>Selenium + headless Chrome</td></tr>
  </table>
  <form action="/get" method="get">
    <input type="text" name="keyword" placeholder="e.g. artificial intelligence" required>
    <button type="submit">Search &amp; summarize</button>
  </form>
</div>
</body>
</html>
"""


@app.get("/")
def index():
    return INDEX_HTML.format(
        registration=REGISTRATION,
        source=NEWS_SOURCE,
        port=PORT,
    )


@app.get("/health")
def health():
    return jsonify({"status": "ok", "registration": REGISTRATION})


@app.get("/debug")
def debug():
    """Troubleshooting view of what the browser sees on the search page."""
    keyword = (request.args.get("keyword") or "technology").strip()
    from scraper import debug_search
    try:
        report = debug_search(keyword)
        report["keyword"] = keyword
        return jsonify(report)
    except Exception as exc:
        log.exception("debug failed")
        return jsonify({"keyword": keyword, "error": str(exc)}), 502


@app.get("/get")
def get():
    keyword = (request.args.get("keyword") or "").strip()

    payload = {
        "registration": REGISTRATION,
        "newssource": NEWS_SOURCE,
        "keyword": keyword,
        "url": "",
        "summary": "",
    }

    if not keyword:
        payload["summary"] = "Missing required query parameter: keyword"
        return jsonify(payload), 400

    log.info("searching %s for keyword=%r", NEWS_SOURCE, keyword)
    try:
        article = scrape(keyword)
        payload["url"] = article["url"]
        summary = summarize(article["text"], max_sentences=SUMMARY_SENTENCES)
        if not summary:
            # Nothing extractable from the body, fall back to the headline.
            summary = article.get("title") or "No summary could be generated."
        payload["summary"] = summary
        log.info("ok route=%s url=%s summary_chars=%d",
                 article.get("route"), payload["url"], len(summary))
        return jsonify(payload)
    except Exception as exc:
        log.exception("scrape failed")
        payload["summary"] = f"Error: {exc}"
        return jsonify(payload), 502


if __name__ == "__main__":
    log.info("starting API on port %d (registration %s, source %s)",
             PORT, REGISTRATION, NEWS_SOURCE)
    app.run(host="0.0.0.0", port=PORT, threaded=True)
