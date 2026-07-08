"""
JKK Tokyo vacancy watcher - GitHub Actions version
-----------------------------------------------------
This is a single-shot version (checks once, then exits) meant to be run
on a schedule by GitHub Actions rather than looping forever like the
desktop version. Alerts are sent via email only, since there's no
desktop to show notifications/sounds on in a cloud runner.

Config is read from environment variables (set as GitHub repo secrets)
instead of hardcoded values, so you don't commit your email password
to the repo.
"""

import os
import sys
import time
import smtplib
from datetime import datetime
from email.mime.text import MIMEText

from playwright.sync_api import sync_playwright

# ======================= CONFIG =======================

WARD_CODE = "3"
WARD_NAME = "Ward 3"

SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "")
SENDER_APP_PASSWORD = os.environ.get("SENDER_APP_PASSWORD", "")
RECIPIENT_EMAIL = os.environ.get("RECIPIENT_EMAIL", "")
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

# ========================================================

BASE_URL = "https://jhomes.to-kousya.or.jp/search/jkknet/service/akiyaChizuInit"

NO_VACANCY_MARKERS = [
    "希望の住宅、またはご希望の条件の空室はございませんでした",
]


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")


def send_email(subject, body):
    if not SENDER_EMAIL or not RECIPIENT_EMAIL:
        log("Email not configured (missing secrets) - skipping alert email.")
        return

    # Support multiple recipients as a comma-separated list in the same secret,
    # e.g. RECIPIENT_EMAIL = "you@gmail.com, spouse@gmail.com, backup@yahoo.com"
    recipients = [addr.strip() for addr in RECIPIENT_EMAIL.split(",") if addr.strip()]
    if not recipients:
        log("No valid recipient addresses found - skipping alert email.")
        return

    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = SENDER_EMAIL
        msg["To"] = ", ".join(recipients)

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_APP_PASSWORD)
            server.sendmail(SENDER_EMAIL, recipients, msg.as_string())
        log(f"Email alert sent to: {', '.join(recipients)}")
    except Exception as e:
        log(f"Email alert failed: {e}")


def find_area_in_context(context, ward_code):
    """
    The real map content opens in a NEW popup window (via window.open),
    not in the original page, and may also use frames within that window.
    So we search every open page, and every frame within each page.
    """
    selector = f"area[onclick*=\"submitPage('{ward_code}')\"]"
    for pg in context.pages:
        for frame in pg.frames:
            try:
                if frame.query_selector(selector):
                    return frame, selector
            except Exception:
                continue
    return None, selector


def collect_text_from_context(context):
    text = ""
    for pg in context.pages:
        for frame in pg.frames:
            try:
                text += frame.inner_text("body") + "\n"
            except Exception:
                continue
    return text


def wait_for_area_in_context(context, ward_code, timeout_seconds=25, poll_interval=1.0):
    """
    Polls repeatedly for the map area element to appear anywhere in any
    open page/frame, since the popup window goes through an intermediate
    loading page (wait.jsp) before the real map content is ready - a
    fixed sleep isn't reliable because that load time varies.
    """
    elapsed = 0.0
    while elapsed < timeout_seconds:
        frame, selector = find_area_in_context(context, ward_code)
        if frame is not None:
            return frame, selector
        time.sleep(poll_interval)
        elapsed += poll_interval
    return None, f"area[onclick*=\"submitPage('{ward_code}')\"]"


def check_once(browser) -> bool:
    context = browser.new_context()
    page = context.new_page()

    page.goto(BASE_URL, wait_until="load")

    frame, selector = wait_for_area_in_context(context, WARD_CODE)

    log(f"Pages open: {[p.url for p in context.pages]}")

    if frame is None:
        log("Could not find the map area element in any open page/frame after "
            "waiting. Dumping first 500 chars of each open page for debugging:")
        for pg in context.pages:
            log(f"--- {pg.url} ---")
            log(pg.content()[:500])
        raise RuntimeError(f"Area element not found for ward code {WARD_CODE}")

    frame.eval_on_selector(selector, "el => el.click()")
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass  # if it never fully idles, we still try reading what's there
    time.sleep(2)  # small buffer for any final rendering

    combined_text = collect_text_from_context(context)
    snippet = combined_text.strip().replace("\n", " ")[:200]
    log(f"Page text snippet: {snippet}")

    no_vacancy = any(marker in combined_text for marker in NO_VACANCY_MARKERS)
    context.close()
    return not no_vacancy


def main():
    log(f"Checking JKK for {WARD_NAME} (code {WARD_CODE})...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            vacancy_found = check_once(browser)
        except Exception as e:
            log(f"Check failed: {e}")
            sys.exit(1)
        finally:
            browser.close()

    if vacancy_found:
        log("!!! POSSIBLE VACANCY FOUND !!!")
        send_email(
            f"JKK Vacancy Alert - {WARD_NAME}",
            f"A possible vacancy was detected in {WARD_NAME} at "
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}.\n\n"
            f"Check: {BASE_URL}"
        )
    else:
        log("No vacancy currently.")


if __name__ == "__main__":
    main()
