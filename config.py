import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 6312016802))
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
OCR_API_KEY = os.getenv("OCR_API_KEY", "")          # ← вот что было пропущено
CASHERA_API_KEY = os.getenv("CASHERA_API_KEY")
CASHERA_SHOP_ID = os.getenv("CASHERA_SHOP_ID", "")
CASHERA_WEBHOOK_SECRET = os.getenv("CASHERA_WEBHOOK_SECRET", "")

FREE_REQUESTS_PER_DAY = 3
VIP_PRICE = 350
VIP_PRICE_RUB = VIP_PRICE