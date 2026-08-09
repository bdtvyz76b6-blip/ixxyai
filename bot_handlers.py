# bot_handlers.py (Groq + Tesseract OCR + контекст + структурированный вывод без каши)
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
from PIL import Image
import pytesseract

groq_client = Groq(api_key=GROQ_API_KEY)

router = Router()
base_webhook_url: str = None

user_requests = {}
last_task = {}  # запоминаем последнюю задачу с фото

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
    """Возвращает структурированный ответ без HTML‑тегов, с чёткими шагами."""
    try:
        completion = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Ты — решатель задач. Решай подробно, шаг за шагом, разделяя шаги пустой строкой. "
                        "Не используй HTML‑теги. В самом конце обязательно напиши окончательный ответ "
                        "ровно в таком формате на отдельной строке: Ответ: <сам ответ>"
                    )
                },
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=1000
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f"❌ Ошибка при решении: {e}"

def split_response(answer: str):
    """Разделяет ответ на основную часть и финальный ответ."""
    # Ищем последнее вхождение строки, начинающейся с "Ответ:"
    idx = answer.rfind("Ответ:")
    if idx != -1:
        main = answer[:idx].strip()
        final = answer[idx:].strip()
        return main, final
    # Если нет "Ответ:", всё считаем основным
    return answer.strip(), None

def ocr_tesseract(image_bytes: bytes) -> str:
    """Распознаёт текст с изображения через Tesseract (без ключа)"""
    try:
        img = Image.open(BytesIO(image_bytes))
        text = pytesseract.image_to_string(img, lang='rus+eng')
        return text.strip()
    except:
        return ""

@router.message(Command("start"))
async def start(message: types.Message):
    base_text = (
        "📚 <b>ixxy AI ГДЗ</b> 🤖\n"
        "Работаю на Groq + Tesseract OCR! Бесплатно и без лимитов.\n\n"
        "🎯 Как пользоваться:\n"
        "• Отправь текстовое сообщение с задачей\n"
        "• Отправь фото с задачей — распознаю и решу!\n"
        "• После фото можно задать уточняющий вопрос\n\n"
        f"🆓 Бесплатно: {FREE_REQUESTS_PER_DAY} задач в день\n"
        f"💎 VIP ({VIP_PRICE}₽ навсегда): безлимит\n\n"
        "/buy — купить VIP\n"
        "/profile — статистика"
    )
    if is_admin(message.from_user.id):
        base_text += "\n/admin — админ-панель"
    await message.answer(base_text, parse_mode=ParseMode.HTML)

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
    remaining = "∞" if is_vip(uid) else str(FREE_REQUESTS_PER_DAY - used)
    await message.answer(
        "<b>Твой профиль</b>\n"
        f"▸ Статус: {vip_status}\n"
        f"▸ Решено сегодня: {used}\n"
        f"▸ Осталось бесплатно: {remaining}",
        parse_mode=ParseMode.HTML
    )

# Решатель текста с учётом контекста
@router.message(F.text & ~F.text.startswith("/"), StateFilter(None))
async def solve_text(message: types.Message, state: FSMContext):
    if not await check_access(message):
        return

    prompt = message.text.strip()
    uid = message.from_user.id

    if uid in last_task and (len(prompt) < 40 or '?' in prompt):
        full_prompt = f"Задача: {last_task[uid]}\nУточняющий вопрос: {prompt}\nОтветь, учитывая условие задачи."
    else:
        full_prompt = prompt

    msg = await message.answer("🧠 Решаю...")
    answer = await solve_groq(full_prompt)

    main_text, final_answer = split_response(answer)
    # Отправляем основную часть (переносы строк сохранятся, без HTML)
    if main_text:
        # Разбиваем длинные сообщения
        for i in range(0, len(main_text), 4000):
            chunk = main_text[i:i+4000]
            if i == 0:
                await msg.edit_text(chunk)
            else:
                await message.answer(chunk)
    else:
        await msg.delete()

    # Отправляем финальный ответ жирным шрифтом
    if final_answer:
        # Удаляем префикс "Ответ:" если есть, чтобы не дублировать
        # final_answer уже содержит "Ответ: ..."
        await message.answer(f"<b>{final_answer}</b>", parse_mode=ParseMode.HTML)

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
        text = ocr_tesseract(img_data)
        if not text:
            await msg.edit_text("❌ Не удалось распознать текст. Попробуй более чёткое фото или напиши вручную.")
            return

        last_task[message.from_user.id] = text

        await msg.edit_text(f"📝 Распознано: {text[:200]}...\n🧠 Решаю...")
        answer = await solve_groq(text)

        main_text, final_answer = split_response(answer)
        if main_text:
            for i in range(0, len(main_text), 4000):
                chunk = main_text[i:i+4000]
                if i == 0:
                    await msg.edit_text(chunk)
                else:
                    await message.answer(chunk)
        else:
            await msg.delete()

        if final_answer:
            await message.answer(f"<b>{final_answer}</b>", parse_mode=ParseMode.HTML)
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка обработки фото: {e}")

# --- Админ-панель (доступ строго по ID) ---
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
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    vips = load_vips()
    text = f"📊 VIP: {len(vips)}\n👥 Сегодня пользователей: {len(user_requests)}"
    await callback.message.edit_text(text)
    await callback.answer()

@router.callback_query(F.data == "admin_give_vip")
async def admin_give_vip_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
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
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    vips = load_vips()
    text = "👑 VIP:\n" + "\n".join(f"• {v}" for v in vips) if vips else "нет"
    await callback.message.edit_text(text)
    await callback.answer()