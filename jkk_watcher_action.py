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
    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = SENDER_EMAIL
        msg["To"] = RECIPIENT_EMAIL

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_APP_PASSWORD)
            server.sendmail(SENDER_EMAIL, [RECIPIENT_EMAIL], msg.as_string())
        log("Email alert sent.")
    except Exception as e:
        log(f"Email alert failed: {e}")


def check_once(page) -> bool:
    page.goto(BASE_URL, wait_until="load")
    page.evaluate(f"submitPage('{WARD_CODE}')")
    page.wait_for_load_state("load")

    text = page.inner_text("body")
    snippet = text.strip().replace("\n", " ")[:200]
    log(f"Page text snippet: {snippet}")

    no_vacancy = any(marker in text for marker in NO_VACANCY_MARKERS)
    return not no_vacancy


def main():
    log(f"Checking JKK for {WARD_NAME} (code {WARD_CODE})...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            vacancy_found = check_once(page)
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
