import os
import requests
from io import BytesIO
from aiogram import Router, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from config import FREE_LIMIT, ADMIN_ID
from vip_manager import (
    is_vip, add_vip, can_use_free, use_free,
    load_vips, save_vips, load_free_usage
)
from payment import create_payment_url

from google import genai
from google.genai.types import Part, GenerateContentConfig

router = Router()
base_webhook_url: str = None

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
MODEL_NAME = "models/gemini-2.0-flash-exp"   # временно рабочая
IMAGE_CONFIG = GenerateContentConfig(response_modalities=["IMAGE", "TEXT"])

class AdminActions(StatesGroup):
    waiting_for_vip_id = State()
    waiting_for_remove_vip_id = State()

def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID

# ==================== ПРОВЕРКА ДОСТУПА ====================
async def check_access(message: types.Message) -> bool:
    uid = message.from_user.id
    if is_vip(uid):
        return True
    if can_use_free(uid):
        use_free(uid)
        return True
    await message.answer(
        f"🎨 Лимит бесплатных генераций исчерпан ({FREE_LIMIT} шт.).\n"
        "Купи вечный VIP за 350₽ — /buy",
        parse_mode=ParseMode.HTML
    )
    return False

# ==================== КОМАНДА /models ====================
@router.message(Command("models"))
async def list_models(message: types.Message):
    try:
        models = client.models.list()
        text = "<b>Доступные модели Gemini:</b>\n\n"
        for model in models:
            if "generateContent" in model.supported_actions:
                name = model.name  # полное имя, например "models/gemini-2.0-flash-exp"
                input_modes = getattr(model, "input_modalities", [])
                output_modes = getattr(model, "output_modalities", [])
                text += f"• <code>{name}</code>\n"
                if input_modes:
                    text += f"  Вход: {', '.join(input_modes)}\n"
                if output_modes:
                    text += f"  Выход: {', '.join(output_modes)}\n"
                text += "\n"
        await message.answer(text, parse_mode=ParseMode.HTML)
    except Exception as e:
        await message.answer(f"❌ Ошибка при получении моделей: {e}")

# ==================== ОСТАЛЬНЫЕ КОМАНДЫ ====================
@router.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "☂️ <b>ixxy AI</b> 🤖\n"
        "Генерирую и редактирую через Gemini 2.0 Flash!\n"
        "Бесплатно, мощно, на русском.\n\n"
        f"🆓 Бесплатно: {FREE_LIMIT} генераций навсегда\n"
        "💎 VIP (350₽ навсегда): безлимит + приоритет\n\n"
        "🎯 Команды:\n"
        "/gen запрос — создать картинку\n"
        "/edit (фото с подписью) — изменить фото\n"
        "/buy — купить VIP\n"
        "/models — список доступных моделей",
        parse_mode=ParseMode.HTML
    )

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

@router.message(Command("gen"))
async def cmd_generate(message: types.Message):
    if not await check_access(message):
        return
    prompt = message.text.partition(" ")[2]
    if not prompt:
        await message.answer("Напиши запрос: /gen киберпанк-кот")
        return

    msg = await message.answer("🎨 Рисую через Gemini... (5–10 сек)")
    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=f"Создай высококачественное, детализированное изображение: {prompt}",
            config=IMAGE_CONFIG
        )
        img_bytes = None
        for part in response.candidates[0].content.parts:
            if part.inline_data and part.inline_data.mime_type.startswith("image/"):
                img_bytes = part.inline_data.data
                break
        if not img_bytes:
            raise Exception("Модель не вернула изображение. Попробуй переформулировать запрос.")
        await message.reply_photo(BufferedInputFile(img_bytes, filename="gemini.jpg"))
        await msg.delete()
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка: {e}")

@router.message(F.photo)
async def handle_photo(message: types.Message):
    if not await check_access(message):
        return
    prompt = message.caption or "сделай стильно, улучши качество"
    file_id = message.photo[-1].file_id
    file = await message.bot.get_file(file_id)
    file_url = f"https://api.telegram.org/file/bot{message.bot.token}/{file.file_path}"

    msg = await message.answer("🔧 Редактирую через Gemini... (5–10 сек)")
    try:
        img_resp = requests.get(file_url)
        img_bytes = img_resp.content

        contents = [
            Part.from_bytes(data=img_bytes, mime_type="image/jpeg"),
            f"Измени это изображение согласно описанию: {prompt}"
        ]
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=contents,
            config=IMAGE_CONFIG
        )
        result_bytes = None
        for part in response.candidates[0].content.parts:
            if part.inline_data and part.inline_data.mime_type.startswith("image/"):
                result_bytes = part.inline_data.data
                break
        if not result_bytes:
            raise Exception("Не удалось отредактировать фото.")
        await message.reply_photo(BufferedInputFile(result_bytes, filename="edited.jpg"))
        await msg.delete()
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка: {e}")

# ==================== АДМИН-ПАНЕЛЬ (как раньше) ====================
# (вставь свою админку, она не менялась)