# Lab Assignment 4 - Selenium News Summarizer API

CSC418 DevOps for Cloud Computing

**Registration:** FA23-BDS-017
**News source:** Ars Technica (`017 % 20 + 1 = 18`)
**Language:** Python (Selenium + headless Google Chrome + ChromeDriver, Flask)
**Docker Hub image:** `huzaimaimtiaz/news-summarizer-api:v1`

## How it works

1. `GET /get?keyword=<kw>` launches headless Chrome through Selenium.
2. Searches Ars Technica and takes the first article result (falls back to a
   site-restricted web search if the on-site search returns nothing).
3. Opens the article, extracts the body text, and produces an extractive summary.
4. Returns JSON: `registration, newssource, keyword, url, summary`.

`GET /` shows the registration number.

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
  "url": "https://arstechnica.com/ai/2026/01/example-article/",
  "summary": "..."
}
```

Also available: `GET /` (registration page), `GET /health`, `GET /debug?keyword=<kw>`
(shows what the browser sees on the search pages, for troubleshooting).

## Files

| File | Purpose |
|---|---|
| `Dockerfile` | Builds the image: Chrome + ChromeDriver + Python app |
| `scraper.py` | Selenium automation (search, first result, article extraction) |
| `summarizer.py` | Summarization module (extractive, dependency free) |
| `app.py` | Flask REST API exposing `/get` on port 7000 |
| `requirements.txt` | Python dependencies |

## Build & run

```bash
docker build -t huzaimaimtiaz/news-summarizer-api:v1 .
docker run -d --name newsapi -p 7000:7000 --shm-size=1g huzaimaimtiaz/news-summarizer-api:v1
curl "http://localhost:7000/get?keyword=artificial%20intelligence"
```

The API service starts automatically when the container runs. The first request
takes longer than later ones because Chrome has to start and load the pages.

## Push

```bash
docker login -u huzaimaimtiaz
docker push huzaimaimtiaz/news-summarizer-api:v1
```
