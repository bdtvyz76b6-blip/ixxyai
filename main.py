import os, asyncio
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from bot_handlers import router
from config import BOT_TOKEN
from payment import verify_webhook_signature   # правильное имя функции
from vip_manager import add_vip

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
dp.include_router(router)

async def handle_cashera(request):
    body = await request.read()
    signature = request.headers.get("X-Cashera-Signature", "")
    if not verify_webhook_signature(body, signature):
        return web.Response(status=403)
    try:
        data = await request.json()
        if data.get("status") == "paid":
            order_id = data.get("order_id", "")
            if order_id.startswith("vip_"):
                user_id = int(order_id.split("_")[1])
                add_vip(user_id)
                await bot.send_message(user_id, "✅ VIP активирован!")
    except:
        return web.Response(status=500)
    return web.Response(text="OK")

async def main():
    port = int(os.environ.get("PORT", 8000))
    app = web.Application()
    app.router.add_post('/cashera-webhook', handle_cashera)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    # Прокидываем base_url для оплаты
    base_url = f"https://{os.environ.get('RAILWAY_PUBLIC_DOMAIN', 'localhost')}"
    import bot_handlers
    bot_handlers.base_webhook_url = base_url
    print(f"Webhook server on {port}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())