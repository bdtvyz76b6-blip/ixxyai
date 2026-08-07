# bot_handlers.py
import asyncio
import replicate
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.enums import ParseMode
from config import REPLICATE_API_TOKEN, FREE_LIMIT
from vip_manager import is_vip, add_vip, can_use_free, use_free
from payment import create_payment_url

router = Router()
replicate_client = replicate.Client(api_token=REPLICATE_API_TOKEN)

# Глобальная переменная для URL вебхука (заполняется из main.py)
base_webhook_url: str = None

# --- Проверка доступа (бесплатные попытки или VIP) ---
async def check_access(message: types.Message) -> bool:
    uid = message.from_user.id
    if is_vip(uid):
        return True
    if can_use_free(uid):
        use_free(uid)
        return True
    await message.answer(
        f"🎨 Ты использовал все {FREE_LIMIT} бесплатные генерации.\n"
        "Купи вечный VIP за 350₽ — /buy",
        parse_mode=ParseMode.HTML
    )
    return False

# --- /start ---
@router.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "☂️ <b>ixxy AI</b> 🤖\n"
        "Генерирую картинки и редактирую фото нейросетями.\n\n"
        f"🆓 Бесплатно: {FREE_LIMIT} генерации навсегда\n"
        "💎 VIP (350₽ навсегда): безлимит + улучшенное качество + видео (скоро)\n\n"
        "🎯 Команды:\n"
        "/gen твой запрос — создать картинку\n"
        "/edit (отправь фото с подписью) — изменить фото\n"
        "/buy — купить VIP",
        parse_mode=ParseMode.HTML
    )

# --- /buy ---
@router.message(Command("buy"))
async def cmd_buy(message: types.Message):
    if not base_webhook_url:
        await message.answer("⚠️ Ошибка конфигурации сервера.")
        return
    url = create_payment_url(message.from_user.id, base_webhook_url)
    if url:
        await message.answer(
            f"💳 <b>VIP навсегда за 350₽</b>\n\n"
            f"👉 <a href='{url}'>Оплатить через cashera.cash</a>\n\n"
            "После оплаты бот пришлёт уведомление.",
            parse_mode=ParseMode.HTML
        )
    else:
        await message.answer("⚠️ Не удалось создать счёт. Попробуй позже.")

# --- /gen ---
@router.message(Command("gen"))
async def cmd_generate(message: types.Message):
    if not await check_access(message):
        return
    prompt = message.text.partition(" ")[2]
    if not prompt:
        await message.answer("Напиши запрос: /gen киберпанк-кот на мотоцикле")
        return
    msg = await message.answer("🎨 Генерирую...")
    try:
        output = replicate_client.run(
            "stability-ai/sdxl:39ed52f2a78e934b3ba6e2a89f5b1c712de7dfea535525255b1aa35c5565e08b",
            input={"prompt": prompt, "width": 768, "height": 768}
        )
        await msg.delete()
        await message.reply_photo(output[0])
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка: {e}")

# --- /edit (или фото с подписью) ---
@router.message(F.photo)
async def handle_photo(message: types.Message):
    if not await check_access(message):
        return
    prompt = message.caption or "улучшить качество, сделать красиво"
    file_id = message.photo[-1].file_id
    file = await message.bot.get_file(file_id)
    file_url = f"https://api.telegram.org/file/bot{message.bot.token}/{file.file_path}"

    msg = await message.answer("🔧 Обрабатываю фото...")
    try:
        output = replicate_client.run(
            "stability-ai/stable-diffusion-img2img:8bea9e8a4d4c3a7e7a5f8f2e8b3c6d1e9a0b4c5d6e7f8a9b0c1d2e3f4a5b6c7",
            input={
                "image": file_url,
                "prompt": prompt,
                "num_inference_steps": 30,
                "guidance_scale": 7.5,
                "strength": 0.75
            }
        )
        await msg.delete()
        await message.reply_photo(output[0])
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка: {e}")