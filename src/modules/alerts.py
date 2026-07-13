import logging
import requests


def send_alert(webhook_url: str, title: str, message: str, enabled: bool = True):
    if not enabled or not webhook_url:
        return
    payload = {"title": title, "message": message}
    try:
        requests.post(webhook_url, json=payload, timeout=10)
    except Exception as e:
        logging.error("Failed to send alert: %s", e)
