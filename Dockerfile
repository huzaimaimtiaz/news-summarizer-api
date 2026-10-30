# Selenium + headless Chrome news scraper / summarizer API
# Registration: FA23-BDS-017   News source: Ars Technica   API port: 7000

FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PORT=7000

# ---------------------------------------------------------------------
# Chrome browser
# Installed from Google's official .deb so apt pulls in every shared
# library that headless Chrome needs.
# ---------------------------------------------------------------------
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      wget ca-certificates unzip fonts-liberation \
 && wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
 && apt-get install -y --no-install-recommends ./google-chrome-stable_current_amd64.deb \
 && rm -f google-chrome-stable_current_amd64.deb \
 && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------
# Chrome driver
# Fetch the chromedriver published for the SAME Chrome major version,
# so the driver and the browser can never drift apart.
# ---------------------------------------------------------------------
RUN set -eux; \
    CHROME_MAJOR="$(google-chrome --version | sed -E 's/.* ([0-9]+)\..*/\1/')"; \
    DRIVER_URL="$(CHROME_MAJOR="$CHROME_MAJOR" python3 -c 'import json,os,urllib.request; m=os.environ["CHROME_MAJOR"]; d=json.load(urllib.request.urlopen("https://googlechromelabs.github.io/chrome-for-testing/known-good-versions-with-downloads.json", timeout=90)); u=[x["url"] for v in d["versions"] if v["version"].split(".")[0]==m for x in (v.get("downloads",{}).get("chromedriver") or []) if x["platform"]=="linux64"]; print(u[-1] if u else "")')"; \
    test -n "$DRIVER_URL"; \
    wget -q -O /tmp/chromedriver.zip "$DRIVER_URL"; \
    unzip -q /tmp/chromedriver.zip -d /tmp; \
    mv /tmp/chromedriver-linux64/chromedriver /usr/local/bin/chromedriver; \
    chmod +x /usr/local/bin/chromedriver; \
    rm -rf /tmp/chromedriver.zip /tmp/chromedriver-linux64; \
    google-chrome --version; \
    chromedriver --version

# ---------------------------------------------------------------------
# Application: Selenium automation + summarization module + REST API
# ---------------------------------------------------------------------
WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY summarizer.py scraper.py app.py ./

EXPOSE 7000

# The API service starts automatically when the container runs.
CMD ["python", "app.py"]
