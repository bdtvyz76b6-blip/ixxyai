import os, requests, asyncio, base64, time
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

# Gemini (только для текста)
from google import genai
from google.genai.types import GenerateContentConfig
gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
TEXT_MODEL = "models/gemini-2.0-flash"

# Replicate (если есть токен)
import replicate
replicate_client = None
if os.getenv("REPLICATE_API_TOKEN"):
    replicate_client = replicate.Client(api_token=os.getenv("REPLICATE_API_TOKEN"))
REPLICATE_MODEL = "stability-ai/sdxl-lightning:8bea9e8a4d4c3a7e7a5f8f2e8b3c6d1e9a0b4c5d6e7f8a9b0c1d2e3f4a5b6c7"

# Stable Horde (запасной)
HORDE_API = "https://stablehorde.net/api/v2/generate/sync"
HORDE_MODEL = "stable_diffusion_xl"

router = Router()
base_webhook_url: str = None

user_modes = {}
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

# ==================== ГЕНЕРАЦИЯ КАРТИНОК (УМНАЯ) ====================
async def generate_image_smart(prompt: str) -> bytes:
    # 1. Pollinations (всегда работает, бесплатно, без ключа)
    try:
        encoded_prompt = requests.utils.quote(prompt)
        url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true"
        resp = requests.get(url, timeout=30)
        if resp.status_code == 200:
            return resp.content
    except:
        pass

    # 2. Stable Horde (бесплатно, без регистрации)
    try:
        payload = {
            "prompt": f"{prompt}, highly detailed",
            "model": HORDE_MODEL,
            "params": {"width": 1024, "height": 1024, "steps": 20}
        }
        resp = requests.post(HORDE_API, json=payload, timeout=60)
        data = resp.json()
        if "img" in data:
            return base64.b64decode(data["img"])
    except:
        pass

    # 3. Replicate (если есть токен)
    if replicate_client:
        try:
            output = replicate_client.run(
                REPLICATE_MODEL,
                input={"prompt": f"{prompt}, cinematic, 8k", "width": 1024, "height": 1024}
            )
            img_url = output[0] if isinstance(output, list) else output
            return requests.get(img_url).content
        except:
            pass

    raise Exception("Все сервисы недоступны. Попробуй позже.")

# ==================== КОМАНДЫ ====================
@router.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "☂️ <b>ixxy AI</b> 🤖\n"
        "Неубиваемый бот: сам переключаю генераторы!\n\n"
        "🎯 Команды:\n"
        "/mode — выбрать режим (Быстрый/Эксперт/Творческий)\n"
        "/ask вопрос — спросить\n"
        "/gen запрос — картинка\n"
        "/buy — купить VIP\n\n"
        f"🆓 Бесплатно: {FREE_LIMIT} картинок, текст безлимит",
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
        full_prompt = f"{mode['prompt']}\n\nПользователь: {prompt}"
        response = gemini_client.models.generate_content(
            model=TEXT_MODEL,
            contents=full_prompt,
            config=GenerateContentConfig(
                temperature=mode['temp'],
                max_output_tokens=mode['max_tokens']
            )
        )
        answer = response.text
        for i in range(0, len(answer), 4000):
            chunk = answer[i:i+4000]
            if i == 0:
                await msg.edit_text(chunk)
            else:
                await message.answer(chunk)
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка: {e}")

@router.message(Command("gen"))
async def cmd_generate(message: types.Message):
    if not await check_access(message):
        return
    prompt = message.text.partition(" ")[2]
    if not prompt:
        await message.answer("Напиши запрос: /gen киберпанк-кот")
        return

    msg = await message.answer("🎨 Генерирую (ищу рабочий сервис)...")
    try:
        img_bytes = await generate_image_smart(prompt)
        await message.reply_photo(BufferedInputFile(img_bytes, filename="img.jpg"))
        await msg.delete()
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка: {e}")

# Редактирование фото временно отключено (можно добавить позже)
@router.message(F.photo)
async def handle_photo(message: types.Message):
    await message.answer("🛠 Редактирование фото временно недоступно. Используй /gen.")

# ==================== АДМИН-ПАНЕЛЬ (как раньше) ====================
# ... вставь свою старую админку без изменений ...