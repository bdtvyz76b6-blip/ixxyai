import os, datetime
from io import BytesIO
import requests as req
from aiogram import Router, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from config import BOT_TOKEN, ADMIN_ID, GEMINI_API_KEY, FREE_REQUESTS_PER_DAY, VIP_PRICE
from vip_manager import is_vip, add_vip, can_use_free, use_free, load_vips, save_vips
from payment import create_payment_url

from google import genai
from google.genai.types import Part

gemini_client = genai.Client(api_key=GEMINI_API_KEY)
MODEL = "models/gemini-2.0-flash"

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

async def solve_math(prompt: str) -> str:
    try:
        response = gemini_client.models.generate_content(
            model=MODEL,
            contents=f"Реши задачу подробно, по шагам, и дай окончательный ответ. Задача: {prompt}"
        )
        return response.text
    except Exception as e:
        return f"❌ Ошибка при решении: {e}"

# ==================== СТАРТ ====================
@router.message(Command("start"))
async def start(message: types.Message):
    await message.answer(
        "📚 <b>ixxy AI ГДЗ</b> 🤖\n"
        "Просто напиши задачу текстом или пришли фото — я решу!\n\n"
        f"🆓 Бесплатно: {FREE_REQUESTS_PER_DAY} задач в день\n"
        f"💎 VIP ({VIP_PRICE}₽ навсегда): безлимит\n\n"
        "🎯 Как пользоваться:\n"
        "• Отправь текстовое сообщение с задачей\n"
        "• Отправь фото (можно с подписью)\n\n"
        "📋 Другие команды:\n"
        "/buy — купить VIP\n"
        "/profile — моя статистика\n"
        "/admin — для администратора",
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

# ==================== РЕШАТЕЛЬ ТЕКСТА ====================
@router.message(F.text & ~F.text.startswith("/"))
async def solve_text(message: types.Message):
    if not await check_access(message):
        return
    prompt = message.text
    msg = await message.answer("🧠 Решаю...")
    answer = await solve_math(prompt)
    await msg.edit_text(answer)

# ==================== РЕШАТЕЛЬ ФОТО ====================
@router.message(F.photo)
async def handle_photo(message: types.Message):
    if not await check_access(message):
        return
    file_id = message.photo[-1].file_id
    file = await message.bot.get_file(file_id)
    file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"
    caption = message.caption or "Реши задачу на фото"

    msg = await message.answer("📷 Распознаю и решаю...")
    try:
        img_data = req.get(file_url).content
        parts = [
            Part.from_bytes(data=img_data, mime_type="image/jpeg"),
            caption
        ]
        response = gemini_client.models.generate_content(
            model=MODEL,
            contents=parts
        )
        answer = response.text
        await msg.edit_text(answer)
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка обработки фото: {e}")

# ==================== АДМИН-ПАНЕЛЬ ====================
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