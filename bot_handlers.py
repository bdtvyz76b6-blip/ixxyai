import os, requests, asyncio
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

# DeepSeek
from openai import OpenAI
deepseek_client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com/v1"
)

# Gemini для картинок
from google import genai
from google.genai.types import Part, GenerateContentConfig
gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
IMAGE_MODEL = "models/gemini-2.0-flash"
IMAGE_CONFIG = GenerateContentConfig(response_modalities=["IMAGE", "TEXT"])

router = Router()
base_webhook_url: str = None

# Хранилище режимов пользователей (user_id -> режим)
user_modes = {}

# Режимы
MODES = {
    "fast": {"name": "⚡ Быстрый", "temp": 0.3, "max_tokens": 200, "prompt": "Отвечай кратко и по делу."},
    "expert": {"name": "🧠 Эксперт", "temp": 0.5, "max_tokens": 800, "prompt": "Отвечай развёрнуто, как эксперт."},
    "creative": {"name": "🎨 Творческий", "temp": 1.0, "max_tokens": 600, "prompt": "Отвечай креативно, с воображением."}
}

class AdminActions(StatesGroup):
    waiting_for_vip_id = State()
    waiting_for_remove_vip_id = State()

def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID

async def check_access(message: types.Message) -> bool:
    uid = message.from_user.id
    if is_vip(uid):
        return True
    if can_use_free(uid):
        use_free(uid)
        return True
    await message.answer(
        f"🎨 Лимит бесплатных генераций исчерпан ({FREE_LIMIT} шт.).\nКупи вечный VIP за 350₽ — /buy",
        parse_mode=ParseMode.HTML
    )
    return False

def get_mode(user_id):
    return user_modes.get(user_id, "fast")

# ==================== КОМАНДЫ ====================
@router.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "☂️ <b>ixxy AI</b> 🤖\n"
        "Выбирай режим и общайся!\n\n"
        "🎯 Команды:\n"
        "/mode — выбор режима (Быстрый/Эксперт/Творческий)\n"
        "/ask вопрос — спросить DeepSeek\n"
        "/gen запрос — создать картинку\n"
        "/edit (фото+подпись) — изменить фото\n"
        "/buy — купить VIP (безлимит картинок)\n\n"
        f"🆓 Текстовые запросы всегда бесплатны. Картинок бесплатно: {FREE_LIMIT}",
        parse_mode=ParseMode.HTML
    )

@router.message(Command("mode"))
async def choose_mode(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚡ Быстрый", callback_data="mode_fast")],
        [InlineKeyboardButton(text="🧠 Эксперт", callback_data="mode_expert")],
        [InlineKeyboardButton(text="🎨 Творческий", callback_data="mode_creative")],
    ])
    current = get_mode(message.from_user.id)
    await message.answer(f"Текущий режим: {MODES[current]['name']}\nВыбери новый:", reply_markup=kb)

@router.callback_query(F.data.startswith("mode_"))
async def set_mode(callback: types.CallbackQuery):
    mode_key = callback.data.split("_", 1)[1]
    user_modes[callback.from_user.id] = mode_key
    await callback.message.edit_text(f"✅ Режим изменён на {MODES[mode_key]['name']}")
    await callback.answer()

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

@router.message(Command("ask"))
async def cmd_ask(message: types.Message):
    prompt = message.text.partition(" ")[2]
    if not prompt:
        await message.answer("Напиши вопрос: /ask что такое нейросеть")
        return

    mode = MODES[get_mode(message.from_user.id)]
    msg = await message.answer(f"🧠 {mode['name']} думает...")
    try:
        response = deepseek_client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": mode['prompt']},
                {"role": "user", "content": prompt}
            ],
            temperature=mode['temp'],
            max_tokens=mode['max_tokens']
        )
        answer = response.choices[0].message.content
        # Разбиваем длинные ответы
        for i in range(0, len(answer), 4000):
            chunk = answer[i:i+4000]
            if i == 0:
                await msg.edit_text(chunk)
            else:
                await message.answer(chunk)
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка DeepSeek: {e}")

# Генерация картинок (Gemini) – без изменений
@router.message(Command("gen"))
async def cmd_generate(message: types.Message):
    if not await check_access(message):
        return
    prompt = message.text.partition(" ")[2]
    if not prompt:
        await message.answer("Напиши запрос: /gen киберпанк-кот")
        return

    msg = await message.answer("🎨 Генерирую...")
    try:
        response = gemini_client.models.generate_content(
            model=IMAGE_MODEL,
            contents=f"Создай высококачественное изображение: {prompt}",
            config=IMAGE_CONFIG
        )
        img_bytes = None
        for part in response.candidates[0].content.parts:
            if part.inline_data and part.inline_data.mime_type.startswith("image/"):
                img_bytes = part.inline_data.data
                break
        if not img_bytes:
            raise Exception("Нет изображения в ответе")
        await message.reply_photo(BufferedInputFile(img_bytes, filename="gen.jpg"))
        await msg.delete()
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка: {e}")

@router.message(F.photo)
async def handle_photo(message: types.Message):
    if not await check_access(message):
        return
    prompt = message.caption or "сделай стильно"
    file_id = message.photo[-1].file_id
    file = await message.bot.get_file(file_id)
    file_url = f"https://api.telegram.org/file/bot{message.bot.token}/{file.file_path}"

    msg = await message.answer("🔧 Редактирую...")
    try:
        img_resp = requests.get(file_url)
        img_bytes = img_resp.content
        contents = [
            Part.from_bytes(data=img_bytes, mime_type="image/jpeg"),
            f"Измени изображение: {prompt}"
        ]
        response = gemini_client.models.generate_content(
            model=IMAGE_MODEL,
            contents=contents,
            config=IMAGE_CONFIG
        )
        result_bytes = None
        for part in response.candidates[0].content.parts:
            if part.inline_data and part.inline_data.mime_type.startswith("image/"):
                result_bytes = part.inline_data.data
                break
        if not result_bytes:
            raise Exception("Не получено")
        await message.reply_photo(BufferedInputFile(result_bytes, filename="edited.jpg"))
        await msg.delete()
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка: {e}")

# Админ-панель остаётся прежней (можно вставить старую)