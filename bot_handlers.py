import os, datetime
from io import BytesIO
import requests as req
from aiogram import Router, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from config import BOT_TOKEN, ADMIN_ID, GROQ_API_KEY, FREE_REQUESTS_PER_DAY, VIP_PRICE
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
            model="llama-3.1-8b-instant",   # или "mixtral-8x7b-32768"
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

# Остальные хендлеры (start, buy, profile, solve_text, handle_photo, admin)
# такие же, как в предыдущих версиях, только вызывай solve_groq(prompt)