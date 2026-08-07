import os
import asyncio
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage   # ← нужно для FSM
from aiogram.types import Update
from bot_handlers import router
from vip_manager import add_vip
from payment import verify_webhook_signature
from config import BOT_TOKEN

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())   # ← включаем хранилище состояний
dp.include_router(router)

async def handle_cashera_webhook(request):
    body = await request.read()
    signature = request.headers.get("X-Cashera-Signature", "")
    if not verify_webhook_signature(body, signature):
        return web.Response(status=403, text="Bad signature")
    try:
        data = await request.json()
        if data.get("status") == "paid":
            order_id = data.get("order_id", "")
            if order_id.startswith("vip_"):
                user_id_str = order_id.split("_")[1]
                user_id = int(user_id_str)
                add_vip(user_id)
                await bot.send_message(user_id, "✅ Оплата получена! VIP доступ открыт навсегда. Жми /gen")
    except Exception as e:
        print("Webhook error:", e)
        return web.Response(status=500)
    return web.Response(text="OK")

async def main():
    port = int(os.environ.get("PORT", 8000))
    app = web.Application()
    app.router.add_post('/cashera-webhook', handle_cashera_webhook)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"Webhook server started on port {port}")

    public_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "localhost")
    base_url = f"https://{public_domain}"
    import bot_handlers
    bot_handlers.base_webhook_url = base_url

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())