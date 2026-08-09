# bot_handlers.py (Groq + OCR, админка без конфликтов)
import os, datetime, base64
import requests as req
from aiogram import Router, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from config import BOT_TOKEN, ADMIN_ID, GROQ_API_KEY, OCR_API_KEY, FREE_REQUESTS_PER_DAY, VIP_PRICE
from vip_manager import is_vip, add_vip, load_vips, save_vips
from payment import create_payment_url

from groq import Groq

groq_client = Groq(api_key=GROQ_API_KEY)

router = Router()
base_webhook_url: str = None

user_requests = {}

class AdminActions(StatesGroup):
    waiting_for_vip_id = State()
    waiting_for_remove_vip_id = State()

def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID

async def check_access(message: types.Message) -> bool:
    uid = message.from_user.id
    if is_vip(uid):
        return True
    today = datetime.date.today()
    info = user_requests.get(uid, {"date": today, "count": 0})
    if info["date"] != today:
        info = {"date": today, "count": 0}
        user_requests[uid] = info
    if info["count"] < FREE_REQUESTS_PER_DAY:
        info["count"] += 1
        user_requests[uid] = info
        return True
    await message.answer(
        f"📚 Дневной лимит исчерпан ({FREE_REQUESTS_PER_DAY} бесплатных решений).\n"
        f"Купи VIP за {VIP_PRICE}₽ — /buy",
        parse_mode=ParseMode.HTML
    )
    return False

async def solve_groq(prompt: str) -> str:
    try:
        completion = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": "Ты — лучший решатель задач. Решай подробно, шаг за шагом, и выдавай окончательный ответ."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=1000
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f"❌ Ошибка при решении: {e}"

async def ocr_space(image_bytes: bytes) -> str:
    """Распознаёт текст с изображения через OCR.space"""
    try:
        apikey = OCR_API_KEY if OCR_API_KEY else "helloworld"
        payload = {
            "apikey": apikey,
            "language": "rus+eng",
            "isOverlayRequired": False,
            "scale": True,
        }
        img_base64 = base64.b64encode(image_bytes).decode("utf-8")
        resp = req.post(
            "https://api.ocr.space/parse/image",
            data={"base64Image": f"data:image/jpeg;base64,{img_base64}", **payload},
            timeout=15
        )
        data = resp.json()
        if data.get("IsErroredOnProcessing"):
            return None
        text = ""
        for result in data.get("ParsedResults", []):
            text += result.get("ParsedText", "")
        return text.strip()
    except:
        return None

@router.message(Command("start"))
async def start(message: types.Message):
    await message.answer(
        "📚 <b>ixxy AI ГДЗ</b> 🤖\n"
        "Работаю на Groq + OCR! Бесплатно и умно.\n\n"
        "🎯 Как пользоваться:\n"
        "• Отправь текстовое сообщение с задачей\n"
        "• Отправь фото с задачей — распознаю и решу!\n\n"
        f"🆓 Бесплатно: {FREE_REQUESTS_PER_DAY} задач в день\n"
        f"💎 VIP ({VIP_PRICE}₽ навсегда): безлимит\n\n"
        "/buy — купить VIP\n"
        "/profile — статистика\n"
        "/admin — админ-панель",
        parse_mode=ParseMode.HTML
    )

@router.message(Command("buy"))
async def buy(message: types.Message):
    if not base_webhook_url:
        await message.answer("⚠️ Ошибка конфигурации.")
        return
    url = create_payment_url(message.from_user.id, base_webhook_url)
    if url:
        await message.answer(
            f"💳 <b>VIP за {VIP_PRICE}₽</b>\n\n"
            f"👉 <a href='{url}'>Оплатить через Cashera</a>\n\n"
            "После оплаты бот активирует VIP.",
            parse_mode=ParseMode.HTML
        )
    else:
        await message.answer("⚠️ Ошибка создания платежа.")

@router.message(Command("profile"))
async def profile(message: types.Message):
    uid = message.from_user.id
    vip_status = "✅ VIP" if is_vip(uid) else "❌ Бесплатный"
    today = datetime.date.today()
    info = user_requests.get(uid, {"date": today, "count": 0})
    used = info["count"] if info["date"] == today else 0
    await message.answer(
        f"👤 Статус: {vip_status}\n"
        f"📆 Сегодня решено: {used}/{FREE_REQUESTS_PER_DAY}"
    )

# ⚡ Вот главное исправление: StateFilter(None) — решаем только если нет активного стейта
@router.message(F.text & ~F.text.startswith("/"), StateFilter(None))
async def solve_text(message: types.Message):
    if not await check_access(message):
        return
    prompt = message.text
    msg = await message.answer("🧠 Решаю...")
    answer = await solve_groq(prompt)
    for i in range(0, len(answer), 4000):
        chunk = answer[i:i+4000]
        if i == 0:
            await msg.edit_text(chunk)
        else:
            await message.answer(chunk)

@router.message(F.photo)
async def handle_photo(message: types.Message):
    if not await check_access(message):
        return
    file_id = message.photo[-1].file_id
    file = await message.bot.get_file(file_id)
    file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"

    msg = await message.answer("📷 Распознаю текст...")
    try:
        img_data = req.get(file_url).content
        text = await ocr_space(img_data)
        if not text:
            await msg.edit_text(
                "❌ Не удалось распознать текст. Пожалуйста, напиши задачу вручную."
            )
            return
        await msg.edit_text(f"📝 Распознано: {text[:200]}...\n🧠 Решаю...")
        answer = await solve_groq(text)
        for i in range(0, len(answer), 4000):
            chunk = answer[i:i+4000]
            if i == 0:
                await msg.edit_text(chunk)
            else:
                await message.answer(chunk)
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка обработки фото: {e}")

def admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="👑 Выдать VIP", callback_data="admin_give_vip")],
        [InlineKeyboardButton(text="📋 Список VIP", callback_data="admin_list_vip")],
    ])

@router.message(Command("admin"))
async def admin_panel(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("🛡 Админ-панель", reply_markup=admin_keyboard())

@router.callback_query(F.data == "admin_stats")
async def admin_stats(callback: types.CallbackQuery):
    vips = load_vips()
    text = f"📊 VIP: {len(vips)}\n👥 Сегодня пользователей: {len(user_requests)}"
    await callback.message.edit_text(text)
    await callback.answer()

@router.callback_query(F.data == "admin_give_vip")
async def admin_give_vip_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminActions.waiting_for_vip_id)
    await callback.message.edit_text("➕ Введите ID пользователя:")
    await callback.answer()

@router.message(StateFilter(AdminActions.waiting_for_vip_id))
async def process_give_vip(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Введите число.")
        return
    uid = int(message.text)
    if is_vip(uid):
        await message.answer("Уже VIP.")
    else:
        add_vip(uid)
        await message.answer(f"✅ {uid} стал VIP!")
        try:
            await message.bot.send_message(uid, "🎉 VIP активирован навсегда!")
        except:
            pass
    await state.clear()

@router.callback_query(F.data == "admin_list_vip")
async def list_vip(callback: types.CallbackQuery):
    vips = load_vips()
    text = "👑 VIP:\n" + "\n".join(f"• {v}" for v in vips) if vips else "нет"
    await callback.message.edit_text(text)
    await callback.answer()