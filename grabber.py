#!/usr/bin/env python3
"""
ff_links_fixed.py — turn fuckingfast.co / buzzheavier.com page links
into direct download links.

    python3 ff_links_fixed.py            # reads fflinks.txt -> ddlinks.txt
    python3 ff_links_fixed.py in.txt out.txt

Why the original broke (all reproduced 2026-11-08 on the test link
https://fuckingfast.co/dqy8n6yocv2t):
  1. Plain requests.get() hits Cloudflare: HTTP 403, "Just a moment..."
     challenge page, not the file page. Sometimes the challenge body is
     cut off mid-stream -> requests ChunkedEncodingError: Response ended
     prematurely, before any parsing happens.
  2. The challenge page has only ONE <script> tag, so
     soup.findAll("script")[2] raises IndexError even when the body
     does arrive.
  3. script[2] never held the link anyway. The current site's real
     mechanism (verified against SilverSpoon's open-source resolver,
     which handles exactly these FitGirl fuckingfast links) is, in
     the browser after Cloudflare clears:
         POST /f/<file_id>/go
         headers: HX-Request: true, HX-Current-URL: <page>, Referer: <page>
         body: cf-turnstile-response=<Turnstile token, or '' if no widget>
     and the direct link comes back in the response header
     "Hx-Redirect". The DOWNLOAD button itself has no href — the page
     even says you must click it twice (first click opens an ad tab).
     Plainly navigating to {page}/download gives "Not Found", which
     is why the bhdownloader-style HEAD /download trick (that works
     on the sister host bzzhr.to, whose button is an hx-get to
     /<code>/download?t=<signed>) does NOT work on fuckingfast.co.
     Filename comes from <title>.
  4. Smaller bugs: the "#" fragment + trailing newline were sent as
     part of the URL, there was no timeout / User-Agent / retry, one
     bad link killed the whole batch, urls[0] would IndexError if no
     URL matched, and writelines() wrote links with no "\n" between
     them, so several links would glue into one line.

Fix strategy, in order per link:
  A. requests (fast path) — browser UA, timeout, retries for the
     flaky chunked response. If it gets the real page, try
     POST /f/<id>/go (empty Turnstile token) and the bzzhr-style
     HEAD {page}/download, either of which answers with hx-redirect.
  B. If Cloudflare challenges the request (403 / "Just a moment"),
     fall back to a real Chromium via Playwright, which passes the
     challenge, reads the Turnstile token from the loaded page, and
     does the POST /f/<id>/go fetch inside the browser (so the
     cf_clearance cookie + token are sent).
       pip install playwright && python -m playwright install chromium
  C. If neither yields hx-redirect, scrape the loaded page HTML for
     a direct link as a last resort.

Requires: requests, beautifulsoup4. Playwright only for path B.
"""

import http.client
import re
import sys
import time
from urllib.parse import urlparse

import requests
import urllib3
from bs4 import BeautifulSoup

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
TIMEOUT = 30
MAX_RETRIES = 3


class CloudflareChallenge(Exception):
    """The page returned Cloudflare's 'Just a moment...' challenge."""


class LinkError(Exception):
    """A link could not be resolved (with a human-readable reason)."""


def clean_url(raw: str) -> str:
    """Strip whitespace/newline and the #fragment (requests sends the
    fragment nowhere useful, and the original sent the raw line)."""
    url = raw.strip()
    return url.split("#", 1)[0].rstrip("/")


def is_challenge(status: int, html: str, headers) -> bool:
    if status == 403 and "cf-mitigated" in str(headers).lower():
        return True
    return "Just a moment" in html or "_cf_chl_opt" in html


def extract_from_html(html: str):
    """Last-resort scrape: any direct link hiding in the page/scripts."""
    soup = BeautifulSoup(html, "html.parser")
    candidates = []
    for a in soup.find_all("a", href=True):
        candidates.append(a["href"])
    for s in soup.find_all("script"):
        if s.string:
            candidates.extend(
                re.findall(r'https?://[^\s"\'()<>]+', s.string))
    for c in candidates:
        if "trashbytes.net/d/" in c or "/download" in c:
            return c
    return None


def get_via_requests(session: requests.Session, page_url: str):
    """Path A: plain requests. Returns (direct_url, filename)."""
    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(page_url,
                               headers={"User-Agent": UA,
                                        "Accept-Encoding": "identity"},
                               timeout=TIMEOUT)
            html = resp.text
            if is_challenge(resp.status_code, html, resp.headers):
                raise CloudflareChallenge(
                    f"HTTP {resp.status_code} Cloudflare challenge")
            resp.raise_for_status()
            break
        except CloudflareChallenge:
            raise
        except (requests.exceptions.RequestException,
                urllib3.exceptions.HTTPError,
                http.client.HTTPException) as e:
            # ChunkedEncodingError / IncompleteRead / ProxyError:
            # the challenge body is often cut off mid-stream, so
            # retry instead of dying on the first truncated read.
            last_exc = e
            print(f"  [requests] attempt {attempt}/{MAX_RETRIES} "
                  f"cut off ({type(e).__name__}: {e}), retrying...",
                  file=sys.stderr)
            time.sleep(2 * attempt)
    else:
        raise LinkError(f"requests failed after retries: {last_exc}")

    soup = BeautifulSoup(html, "html.parser")
    filename = (soup.title.string.strip()
                if soup.title and soup.title.string else "")
    file_id = urlparse(page_url).path.strip("/").split("/")[0]

    # Mechanism 1 (fuckingfast.co): POST /f/<id>/go, hx-redirect back.
    # No Turnstile token is available to plain requests, so this only
    # works when the page had no widget; the browser path below is
    # the one that can actually supply a token.
    go = session.post(
        f"{urlparse(page_url).scheme}://{urlparse(page_url).netloc}"
        f"/f/{file_id}/go",
        headers={"User-Agent": UA, "HX-Request": "true",
                 "HX-Target": "", "HX-Current-URL": page_url,
                 "Referer": page_url},
        data={"cf-turnstile-response": ""},
        allow_redirects=False, timeout=TIMEOUT,
    )
    hx = go.headers.get("hx-redirect") or go.headers.get("Hx-Redirect")
    if go.status_code == 200 and hx:
        return _abs(hx, page_url), filename

    # Mechanism 2 (sister host bzzhr.to / buzzheavier): the download
    # button is an hx-get to /<code>/download?t=<signed>, answering
    # 204 with HX-Redirect. Kept as a fallback; on fuckingfast.co
    # a plain GET of /download is "Not Found".
    head = session.head(
        page_url.rstrip("/") + "/download",
        headers={"User-Agent": UA,
                 "hx-current-url": page_url,
                 "hx-request": "true",
                 "referer": page_url},
        allow_redirects=False, timeout=TIMEOUT,
    )
    if head.status_code == 403:
        raise CloudflareChallenge("HTTP 403 on HEAD /download")
    hx = head.headers.get("hx-redirect") or head.headers.get("Location")
    if hx:
        return _abs(hx, page_url), filename

    fallback = extract_from_html(html)
    if fallback:
        return fallback, filename
    raise LinkError("no hx-redirect from POST /f/<id>/go or HEAD "
                    "/download, and no direct link in page HTML")


def _abs(url: str, page_url: str) -> str:
    if url.startswith("/"):
        p = urlparse(page_url)
        return f"{p.scheme}://{p.netloc}{url}"
    return url


def get_via_browser(page_url: str):
    """Path B: real Chromium (Playwright) — passes the Cloudflare
    challenge, reads the Turnstile token, then POSTs /f/<id>/go
    inside the page (cf_clearance cookie + token are sent), and
    reads the direct link from the Hx-Redirect header.
    Mirrors SilverSpoon's _resolve_fuckingfast_async."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise LinkError(
            "Cloudflare challenge + Playwright not installed: "
            "pip install playwright && python -m playwright install chromium"
        ) from e

    file_id = urlparse(page_url).path.strip("/").split("/")[0]
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled",
                  "--no-sandbox", "--disable-dev-shm-usage"],
        )
        ctx = browser.new_context(user_agent=UA,
                                  viewport={"width": 1280, "height": 800},
                                  ignore_https_errors=True)
        page = ctx.new_page()
        try:
            page.goto(page_url, wait_until="domcontentloaded", timeout=60000)
            try:
                page.wait_for_function(
                    "document.title && !document.title.includes('Just a moment')",
                    timeout=60000)
            except Exception as e:
                raise LinkError(f"Cloudflare challenge did not clear: {e}")
            filename = page.title()

            # Turnstile token, if the page shows a widget; wait for it.
            token = ""
            has_widget = page.evaluate(
                "!!(document.querySelector('.cf-turnstile') || "
                "document.querySelector('[name=\"cf-turnstile-response\"]') || "
                "document.querySelector('iframe[src*=\"turnstile\"]'))")
            if has_widget:
                for _ in range(60):
                    token = page.evaluate(
                        "window.turnstileToken || "
                        "document.querySelector('[name=\"cf-turnstile-response\"]')"
                        "?.value || ''")
                    if len(token) > 20:
                        break
                    page.wait_for_timeout(1000)
                if len(token) <= 20:
                    raise LinkError(
                        "Turnstile check did not complete in 60s")

            result = page.evaluate(
                """async ([fid, link, tok]) => {
                    const r = await fetch('/f/' + fid + '/go', {
                        method: 'POST',
                        headers: {'HX-Request': 'true', 'HX-Target': '',
                                  'HX-Current-URL': link, 'Referer': link},
                        body: new URLSearchParams(
                            {'cf-turnstile-response': tok})});
                    return {status: r.status,
                            hx: r.headers.get('Hx-Redirect')
                                || r.headers.get('hx-redirect'),
                            body: (await r.text()).slice(0, 200)};
                }""",
                [file_id, page_url, token])
            if result.get("status") == 200 and result.get("hx"):
                return _abs(result["hx"], page_url), filename
            raise LinkError(
                f"POST /f/{file_id}/go returned HTTP "
                f"{result.get('status')}, no Hx-Redirect. "
                f"Response: {result.get('body', '')}")
        finally:
            browser.close()


def resolve_one(page_url: str) -> str:
    """Resolve one page link to its direct download link."""
    with requests.Session() as session:
        try:
            direct, filename = get_via_requests(session, page_url)
            print(f"  [requests] {filename or page_url} -> {direct}")
            return direct
        except (CloudflareChallenge, LinkError) as e:
            # Requests either got challenged, or reached the page but
            # could not resolve it (e.g. POST /go needs a Turnstile
            # token only a browser can produce) — the browser path
            # below is the one that can supply that token.
            print(f"  [requests] {e} — falling back to real browser...",
                  file=sys.stderr)
    direct, filename = get_via_browser(page_url)
    print(f"  [browser] {filename or page_url} -> {direct}")
    return direct


def main(argv):
    in_file = argv[1] if len(argv) > 1 else "fflinks.txt"
    out_file = argv[2] if len(argv) > 2 else "ddlinks.txt"

    try:
        raw_lines = open(in_file, encoding="utf-8").read().splitlines()
    except FileNotFoundError:
        print(f"error: input file not found: {in_file}", file=sys.stderr)
        return 2

    links = [clean_url(l) for l in raw_lines
             if l.strip() and not l.strip().startswith("#")]
    if not links:
        print(f"error: no links in {in_file}", file=sys.stderr)
        return 2

    resolved, failed = [], 0
    for link in links:
        print(f"Resolving {link}")
        try:
            resolved.append(resolve_one(link))
        except Exception as e:  # per-link: one bad link no longer
            print(f"  FAILED {link}: {e}", file=sys.stderr)  # kills batch
            failed += 1

    with open(out_file, "w", encoding="utf-8") as f:
        for url in resolved:
            f.write(url + "\n")   # original wrote no "\n" at all

    print(f"\nDone: {len(resolved)} ok, {failed} failed -> {out_file}")
    return 1 if failed and not resolved else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
