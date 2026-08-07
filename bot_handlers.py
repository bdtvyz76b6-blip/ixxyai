# bot_handlers.py
import asyncio
import os
from io import BytesIO
import requests
from aiogram import Router, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import FREE_LIMIT, ADMIN_ID, HF_TOKEN
from vip_manager import (
    is_vip, add_vip, can_use_free, use_free,
    load_vips, save_vips, load_free_usage
)
from payment import create_payment_url

router = Router()
base_webhook_url: str = None

# Инициализация клиента Hugging Face
from huggingface_hub import InferenceClient
hf_client = InferenceClient(token=HF_TOKEN)

# Модели (бесплатные, проверенные)
TEXT2IMG_MODEL = "stabilityai/stable-diffusion-xl-base-1.0"   # генерация по тексту
IMG2IMG_MODEL = "stabilityai/stable-diffusion-xl-refiner-1.0" # редактирование фото

# Состояния для админки
class AdminActions(StatesGroup):
    waiting_for_vip_id = State()
    waiting_for_remove_vip_id = State()

def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID

# ==================== ОБЫЧНЫЕ КОМАНДЫ ====================
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

@router.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "☂️ <b>ixxy AI</b> 🤖\n"
        "Бесплатные нейросети на борту!\n\n"
        f"🆓 Бесплатно: {FREE_LIMIT} генерации навсегда\n"
        "💎 VIP (350₽ навсегда): безлимит + улучшенное качество\n\n"
        "🎯 Команды:\n"
        "/gen твой запрос — создать картинку\n"
        "/edit (отправь фото с подписью) — изменить фото\n"
        "/buy — купить VIP",
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
        await message.answer("Напиши запрос: /gen киберпанк-кот на мотоцикле")
        return
    msg = await message.answer("🎨 Генерирую... (бесплатно, может занять до 30 сек)")
    try:
        # Генерация через Hugging Face
        image = hf_client.text_to_image(prompt, model=TEXT2IMG_MODEL)
        # Конвертируем в байты для отправки
        bio = BytesIO()
        image.save(bio, format="JPEG")
        bio.seek(0)
        await msg.delete()
        await message.reply_photo(bio)
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка: {e}")

@router.message(F.photo)
async def handle_photo(message: types.Message):
    if not await check_access(message):
        return
    prompt = message.caption or "улучшить качество, сделать красиво"
    # Получаем фото
    file_id = message.photo[-1].file_id
    file = await message.bot.get_file(file_id)
    file_url = f"https://api.telegram.org/file/bot{message.bot.token}/{file.file_path}"

    msg = await message.answer("🔧 Обрабатываю фото... (бесплатно, до 40 сек)")
    try:
        # Скачиваем изображение в память
        response = requests.get(file_url)
        image_bytes = response.content

        # Отправляем на img2img через Inference API
        # Используем модель refiner (она умеет image+prompt)
        output_image = hf_client.image_to_image(
            image=image_bytes,
            prompt=prompt,
            model=IMG2IMG_MODEL,
            strength=0.75,
            guidance_scale=7.5
        )
        bio = BytesIO()
        output_image.save(bio, format="JPEG")
        bio.seek(0)
        await msg.delete()
        await message.reply_photo(bio)
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка: {e}")

# ==================== АДМИН-ПАНЕЛЬ (без изменений) ====================
# ... оставь как было, с кнопками и состояниями ...