#!/usr/bin/env python3
"""
WEBSITE MONITOR - CONTINUOUS MODE
- Runs forever until Ctrl+C
- Checks every minute for immediate DOWN alerts
- Sends status email every 10 minutes (if all fine) or immediately (if issues)
"""

import os
import sys
import json
import time
import logging
import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage

# =====================================================
# CONFIGURATION - EDIT THESE
# =====================================================

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = "example@gamil.com"
SMTP_PASSWORD = "example"   # <-- PUT YOUR GMAIL APP PASSWORD HERE
RECEIVER_EMAIL = "example@gamil.com"

WEBSITES_TO_MONITOR = [
    {"name": "Google", "url": "https://www.google.com"},
    {"name": "Cloudflare", "url": "https://www.cloudflare.com"},
    {"name": "Wikipedia", "url": "https://www.wikipedia.org"},
]

# Timing settings
CHECK_INTERVAL = 60          # seconds between each check (1 minute)
STATUS_INTERVAL = 10         # minutes between status emails
TIMEOUT = 10                 # seconds to wait for website response
RETRY_COUNT = 2              # retry twice before declaring down
RETRY_DELAY = 3              # seconds between retries

# File paths
STATE_FILE = "monitor_state.json"
LOG_FILE = "monitor.log"
LAST_STATUS_FILE = "last_status_email.txt"

# =====================================================
#  DON'T EDIT BELOW
# =====================================================

# Setup logging WITHOUT emojis for Windows compatibility
class NoEmojiFilter(logging.Filter):
    def filter(self, record):
        # Remove emojis from log messages (they cause errors on Windows)
        record.msg = record.msg.replace("🚀", "[START]")
        record.msg = record.msg.replace("✅", "[OK]")
        record.msg = record.msg.replace("❌", "[FAIL]")
        record.msg = record.msg.replace("⚠️", "[WARN]")
        record.msg = record.msg.replace("🎉", "[DONE]")
        record.msg = record.msg.replace("📧", "[EMAIL]")
        return True

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)
logger.addFilter(NoEmojiFilter())

try:
    import requests
except ImportError:
    logger.error("[ERROR] 'requests' library not found. Run: pip install requests")
    sys.exit(1)

# ---- Helper functions ----
def get_last_status_time():
    if os.path.exists(LAST_STATUS_FILE):
        try:
            with open(LAST_STATUS_FILE, "r") as f:
                return datetime.fromisoformat(f.read().strip())
        except:
            return None
    return None

def save_last_status_time():
    with open(LAST_STATUS_FILE, "w") as f:
        f.write(datetime.now().isoformat())

def should_send_status_email():
    last_time = get_last_status_time()
    if last_time is None:
        return True
    return datetime.now() - last_time >= timedelta(minutes=STATUS_INTERVAL)

# ---- Core check functions ----
def check_website(url, timeout):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        resp = requests.get(url, timeout=timeout, allow_redirects=True, headers=headers)
        if 200 <= resp.status_code < 300:
            return True, f"Status {resp.status_code}"
        else:
            return False, f"HTTP {resp.status_code}"
    except requests.exceptions.Timeout:
        return False, "Timeout"
    except requests.exceptions.ConnectionError:
        return False, "DNS/Network error"
    except requests.exceptions.SSLError:
        return False, "SSL Certificate error"
    except Exception as e:
        return False, f"Error: {str(e)}"

def check_with_retry(check_func, *args, **kwargs):
    last_msg = "Unknown"
    for attempt in range(1, RETRY_COUNT + 1):
        is_up, msg = check_func(*args, **kwargs)
        if is_up:
            return True, msg
        last_msg = msg
        if attempt < RETRY_COUNT:
            logger.info(f"Retry {attempt}/{RETRY_COUNT} failed. Waiting {RETRY_DELAY}s...")
            time.sleep(RETRY_DELAY)
    return False, last_msg

# ---- State management ----
def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

# ---- Email functions (emojis are fine in emails) ----
def send_email(subject, body):
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = SMTP_USER
        msg["To"] = RECEIVER_EMAIL
        msg.set_content(body)

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        logger.info(f"[EMAIL] Sent: {subject}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return False

def send_immediate_alert(down_sites, recovered_sites):
    if down_sites:
        body = f"🚨 IMMEDIATE ALERT - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        body += "=" * 50 + "\n\n"
        body += "❌ The following websites are DOWN:\n\n"
        for site in down_sites:
            body += f"  - {site['name']} ({site['url']})\n"
            body += f"    Reason: {site['message']}\n\n"
        body += "⚠️ Please check immediately!"

        subject = f"🚨 URGENT: {len(down_sites)} Website(s) are DOWN!"
        send_email(subject, body)

    if recovered_sites:
        body = f"✅ RECOVERY ALERT - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        body += "=" * 50 + "\n\n"
        body += "The following websites have RECOVERED:\n\n"
        for site in recovered_sites:
            body += f"  - {site['name']} ({site['url']})\n"
            body += f"    Status: Back to normal!\n\n"
        body += "✅ All systems are operational."

        subject = f"✅ RECOVERED: {len(recovered_sites)} Website(s) are back UP!"
        send_email(subject, body)

def send_status_email(all_up):
    body = f"📊 STATUS UPDATE - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    body += "=" * 50 + "\n\n"

    state = load_state()
    if all_up:
        body += "✅✅✅ ALL WEBSITES ARE OPERATIONAL! ✅✅✅\n\n"
        for site in WEBSITES_TO_MONITOR:
            body += f"  ✅ {site['name']} - {site['url']} - UP\n"
        body += "\nNo issues detected. Everything is running smoothly."
    else:
        body += "⚠️ SOME WEBSITES ARE DOWN\n\n"
        for site in WEBSITES_TO_MONITOR:
            item_id = f"web_{site['url']}"
            status = state.get(item_id, "UNKNOWN")
            icon = "✅" if status == "UP" else "❌"
            body += f"  {icon} {site['name']} - {site['url']} - {status}\n"

    subject = "📊 STATUS REPORT: All Websites are UP!" if all_up else "📊 STATUS REPORT: Some Websites are DOWN"
    send_email(subject, body)

# ---- Main monitoring loop (runs forever) ----
def main_loop():
    logger.info("=" * 60)
    logger.info("[START] Starting Continuous Website Monitor...")
    logger.info(f"Checking every {CHECK_INTERVAL} seconds.")
    logger.info("Press Ctrl+C to stop.\n")

    while True:
        try:
            state = load_state()
            current_state = {}
            down_sites = []
            recovered_sites = []
            all_up = True

            # Check all websites
            for site in WEBSITES_TO_MONITOR:
                item_id = f"web_{site['url']}"
                name = site["name"]
                url = site["url"]

                logger.info(f"Checking: {name} ({url})...")
                is_up, msg = check_with_retry(check_website, url, TIMEOUT)

                current_state[item_id] = "UP" if is_up else "DOWN"
                prev_state = state.get(item_id, "UP")

                if is_up and prev_state == "DOWN":
                    recovered_sites.append({"name": name, "url": url, "message": msg})
                    logger.info(f"[OK] {name} RECOVERED!")
                elif not is_up and prev_state == "UP":
                    down_sites.append({"name": name, "url": url, "message": msg})
                    logger.warning(f"[FAIL] {name} WENT DOWN! Reason: {msg}")
                    all_up = False
                elif not is_up:
                    logger.warning(f"[WARN] {name} still DOWN. (No new alert)")
                    all_up = False
                else:
                    logger.info(f"[OK] {name} is UP.")

            # Send immediate alerts for DOWN or RECOVERED sites
            if down_sites or recovered_sites:
                send_immediate_alert(down_sites, recovered_sites)

            # Send periodic status email (every 10 minutes) if all is fine
            if all_up and should_send_status_email():
                send_status_email(all_up=True)
                save_last_status_time()
            elif not all_up:
                send_status_email(all_up=False)
                save_last_status_time()

            # Save state
            save_state(current_state)
            logger.info(f"Scan complete. Next check in {CHECK_INTERVAL} seconds.\n")

            # Wait for the next check interval
            time.sleep(CHECK_INTERVAL)

        except KeyboardInterrupt:
            logger.info("\n[STOP] Monitoring stopped by user.")
            break
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            logger.info(f"Waiting {CHECK_INTERVAL} seconds before retry...")
            time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main_loop()
