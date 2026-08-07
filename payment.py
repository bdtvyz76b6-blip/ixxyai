import requests
import time
import hmac
import hashlib
from config import (
    CASHERA_API_KEY, CASHERA_SHOP_ID, VIP_PRICE_RUB,
    CASHERA_WEBHOOK_SECRET, BOT_TOKEN
)

def create_payment_url(user_id: int, webhook_base_url: str) -> str | None:
    order_id = f"vip_{user_id}_{int(time.time())}"
    payload = {
        "amount": VIP_PRICE_RUB,
        "currency": "RUB",
        "order_id": order_id,
        "description": "☂️ ixxy AI VIP навсегда",
        "success_url": f"https://t.me/{(BOT_TOKEN.split(':'))[0]}",
        "cancel_url": f"https://t.me/{(BOT_TOKEN.split(':'))[0]}",
        "webhook_url": f"{webhook_base_url}/cashera-webhook"
    }
    headers = {
        "Authorization": f"Bearer {CASHERA_API_KEY}",
        "Content-Type": "application/json"
    }
    try:
        r = requests.post("https://api.cashera.cash/v1/invoice", json=payload, headers=headers)
        data = r.json()
        if data.get("success"):
            return data["result"]["pay_url"]
        else:
            print("Cashera error:", data)
            return None
    except Exception as e:
        print("Network error:", e)
        return None

def verify_webhook_signature(request_body: bytes, signature: str) -> bool:
    if not CASHERA_WEBHOOK_SECRET:
        return True
    expected = hmac.new(
        CASHERA_WEBHOOK_SECRET.encode(),
        request_body,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)