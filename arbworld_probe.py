import re
import sys
import json
import time
import subprocess
import requests
from html import unescape

URL = "https://arbworld.net/for-webmasters/moneyway/football-1-x-2.php"

TARGETS = [
    ("Sporting", "Galatasaray"),
    ("Napoli", "Arsenal"),
    ("Liverpool", "Atletico"),
    ("Barcelona", "Feyenoord"),
]

def clean_text(text):
    text = unescape(text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text

def show_targets(text, label):
    low = text.lower()
    print(f"\n===== {label} =====")
    found_any = False
    for home, away in TARGETS:
        i = low.find(home.lower())
        j = low.find(away.lower(), i + 1) if i >= 0 else -1
        if i >= 0 and j >= 0:
            found_any = True
            start = max(0, i - 220)
            end = min(len(text), j + 650)
            print(f"\nMATCH {home} - {away}:")
            print(text[start:end])
        else:
            print(f"\nMATCH {home} - {away}: NOT FOUND")
    return found_any

# 1) Baseline static request
headers = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

r = requests.get(URL, headers=headers, timeout=30)
print("STATIC STATUS:", r.status_code)
print("STATIC BYTES:", len(r.text))

static_plain = re.sub(r"<script[\s\S]*?</script>", " ", r.text, flags=re.I)
static_plain = re.sub(r"<style[\s\S]*?</style>", " ", static_plain, flags=re.I)
static_plain = re.sub(r"<[^>]+>", " ", static_plain)
static_plain = clean_text(static_plain)
show_targets(static_plain, "STATIC HTML")

# 2) Browser-rendered test
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
except ImportError:
    print("\nInstalling Selenium...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "selenium"])
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

options = Options()
options.add_argument("--headless=new")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
options.add_argument("--disable-gpu")
options.add_argument("--window-size=1920,3000")
options.add_argument("--lang=en-US")
options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

driver = None

try:
    print("\nStarting headless Chrome...")
    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(45)
    driver.get(URL)

    # Let JavaScript/AJAX populate the table.
    for sec in (3, 6, 10, 15):
        time.sleep(sec if sec == 3 else sec - prev)
        prev = sec
        body = clean_text(driver.find_element("tag name", "body").text)
        print(f"BROWSER AFTER {sec}s: text chars={len(body)}")
        if any(h.lower() in body.lower() for h, _ in TARGETS):
            break

    body = clean_text(driver.find_element("tag name", "body").text)
    found = show_targets(body, "BROWSER RENDERED TEXT")

    print("\nBROWSER TEXT HEAD:")
    print(body[:5000])

    # Show likely data endpoints requested by the page.
    print("\nLIKELY NETWORK DATA URLS:")
    seen = set()
    try:
        logs = driver.get_log("performance")
        for entry in logs:
            msg = json.loads(entry["message"])["message"]
            if msg.get("method") != "Network.responseReceived":
                continue
            resp = msg.get("params", {}).get("response", {})
            url = resp.get("url", "")
            ctype = (resp.get("mimeType") or "").lower()
            key = url.lower()
            if (
                "arbworld" in key
                and (
                    "moneyway" in key
                    or "ajax" in key
                    or "api" in key
                    or "json" in key
                    or "data" in key
                    or "php" in key
                )
            ):
                if url not in seen:
                    seen.add(url)
                    print(ctype, url)
    except Exception as e:
        print("Network-log read error:", repr(e))

    print("\nRESULT:", "LIVE ROWS FOUND" if found else "LIVE ROWS NOT FOUND")

finally:
    if driver:
        driver.quit()
