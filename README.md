# Lab Assignment 4 - Selenium News Summarizer API

CSC418 DevOps for Cloud Computing

**Registration:** FA23-BDS-017
**News source:** Ars Technica (`017 % 20 + 1 = 18`)
**Language:** Python (Selenium + headless Google Chrome + ChromeDriver, Flask)
**Docker Hub image:** `huzaimaimtiaz/news-summarizer-api:v1`

## How it works

1. `GET /get?keyword=<kw>` launches headless Chrome through Selenium.
2. Finds the first matching Ars Technica article for the keyword.
3. Opens that article in Chrome and extracts the body text.
4. Summarizes it with the extractive summarizer in `summarizer.py`.
5. Returns JSON: `registration, newssource, keyword, url, summary`.

`GET /` shows the registration number.

### Search strategy

Ars Technica puts a bot interstitial in front of its HTML pages, which can
appear for cloud/datacenter IP addresses. The scraper is therefore layered and
uses whichever route works:

1. The site's own search page, driven by Chrome, waiting for any interstitial
   to clear before reading the results.
2. A site-restricted web search.
3. The site's public RSS section feeds, which are not behind the interstitial,
   aggregated and keyword-matched to locate the article.

Once the article is located, Chrome opens that article page and scrapes its
text. The feed summary is only used if the article page itself cannot be
rendered.

## API

**Endpoint:** `GET /get` **Port:** 7000 **Query parameter:** `keyword` (string)

```
http://<HOST_IP>:7000/get?keyword=artificial%20intelligence
```

```json
{
  "registration": "FA23-BDS-017",
  "newssource": "Ars Technica",
  "keyword": "artificial intelligence",
  "url": "https://arstechnica.com/ai/2026/10/example-article/",
  "summary": "..."
}
```

Also available: `GET /` (registration page), `GET /health`, and
`GET /debug?keyword=<kw>` which reports what the browser sees on each search
page plus the feed status, for troubleshooting.

## Files

| File | Purpose |
|---|---|
| `Dockerfile` | Builds the image: Chrome + ChromeDriver + Python app |
| `scraper.py` | Selenium automation (search, article open, text extraction) |
| `summarizer.py` | Summarization module (extractive, dependency free) |
| `app.py` | Flask REST API exposing `/get` on port 7000 |
| `requirements.txt` | Python dependencies |

## Build & run

```bash
docker build -t huzaimaimtiaz/news-summarizer-api:v1 .
docker run -d --name newsapi -p 7000:7000 --shm-size=1g huzaimaimtiaz/news-summarizer-api:v1
curl "http://localhost:7000/get?keyword=artificial%20intelligence"
```

The API service starts automatically when the container runs. The first
request takes longer because Chrome has to start and load the pages.

## Push

```bash
docker login -u huzaimaimtiaz
docker push huzaimaimtiaz/news-summarizer-api:v1
```
