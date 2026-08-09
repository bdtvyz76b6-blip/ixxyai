import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 6312016802))   # твой ID, оставь как есть
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")        # обязательно добавь в Railway!
CASHERA_API_KEY = os.getenv("CASHERA_API_KEY")
CASHERA_WEBHOOK_SECRET = os.getenv("CASHERA_WEBHOOK_SECRET", "")

# Настройки ГДЗ-бота
FREE_REQUESTS_PER_DAY = 3   # бесплатных решений в день
VIP_PRICE = 350              # цена VIP в рублях