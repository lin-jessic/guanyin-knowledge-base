"""Optional Selenium fallback for JavaScript-rendered or bot-challenged pages.

The normal crawler remains requests-based. This module is imported lazily only
when a page looks like an empty JS shell or returns a browser challenge, so a
machine without Selenium can still run the ordinary static-page pipeline.
"""
from __future__ import annotations

import time
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup


CHROME_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    seen, result = set(), []
    for anchor in soup.select("a[href]"):
        href = urljoin(base_url, anchor.get("href", "")).split("#", 1)[0]
        if urlsplit(href).scheme not in {"http", "https"} or href in seen:
            continue
        seen.add(href)
        result.append(href)
    return result


def render_page(url: str, timeout: int = 30, settle_seconds: float = 2.0) -> dict:
    """Render a page in headless Chrome and return fetcher-compatible fields.

    Selenium Manager finds the locally installed Chrome and matching driver.
    Any browser setup or navigation error is raised to the caller, which keeps
    the original requests result and records a review reason.
    """
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.support.ui import WebDriverWait
    except ImportError as exc:  # pragma: no cover - depends on optional install
        raise RuntimeError("未安裝 Selenium；請執行 pip install -r requirements.txt") from exc

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1440,2200")
    options.add_argument(f"--user-agent={CHROME_USER_AGENT}")
    driver = webdriver.Chrome(options=options)
    started = time.monotonic()
    try:
        driver.set_page_load_timeout(timeout)
        driver.get(url)
        WebDriverWait(driver, timeout).until(
            lambda d: d.execute_script("return document.readyState") in {"interactive", "complete"}
        )
        # Trigger common lazy-loading implementations without an unbounded wait.
        for fraction in (0.35, 0.7, 1.0):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight * arguments[0]);", fraction)
            time.sleep(0.35)
        time.sleep(max(0.0, settle_seconds))
        html = driver.page_source
        final_url = driver.current_url or url
        title = driver.title or ""
        return {
            "html": html,
            "final_url": final_url,
            "title": title,
            "links": _links(html, final_url),
            "image_headers": {
                "User-Agent": CHROME_USER_AGENT,
                "Referer": final_url,
                "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
                "Sec-Fetch-Dest": "image",
                "Sec-Fetch-Mode": "no-cors",
                "Sec-Fetch-Site": "cross-site",
            },
            "elapsed_ms": round((time.monotonic() - started) * 1000),
        }
    finally:
        driver.quit()

