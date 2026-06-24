"""Run: py debug_playwright.py
Tests Playwright on the GC page and saves a screenshot to see what's actually rendered.
"""
from playwright.sync_api import sync_playwright
import http.cookiejar, urllib.request

BASE_URL = "https://www.procyclingstats.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-GB,en;q=0.9",
}

# Get session cookie via urllib
cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
req = urllib.request.Request(BASE_URL + "/race/tour-auvergne-rhone-alpes/2026/gc", headers=HEADERS)
with opener.open(req, timeout=15) as r:
    r.read()
cookies = [{"name": c.name, "value": c.value, "domain": "www.procyclingstats.com", "path": "/"}
           for c in cj]
print(f"Cookies: {[c['name'] for c in cookies]}")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    )
    if cookies:
        ctx.add_cookies(cookies)
    page = ctx.new_page()

    url = BASE_URL + "/race/tour-auvergne-rhone-alpes/2026/gc"
    print(f"Navigating to {url} ...")
    page.goto(url, wait_until="domcontentloaded", timeout=15000)
    print("Page loaded. Waiting 5s for JS...")
    page.wait_for_timeout(5000)

    # Screenshot to see what's rendered
    page.screenshot(path="debug_playwright.png")
    print("Screenshot saved: debug_playwright.png")

    # Check cont divs
    cont_text = page.evaluate("""() => {
        const divs = document.querySelectorAll('td.ridername div.cont');
        return Array.from(divs).slice(0,3).map(d => d.textContent.trim());
    }""")
    print(f"First 3 cont div texts: {cont_text}")

    # Check page title
    print(f"Page title: {page.title()}")

    browser.close()
