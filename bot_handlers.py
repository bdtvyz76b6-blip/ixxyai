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
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
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

# Проверенные бесплатные модели (работают с read-токеном)
TEXT2IMG_MODEL = "runwayml/stable-diffusion-v1-5"   # генерация
IMG2IMG_MODEL = "runwayml/stable-diffusion-v1-5"    # редактирование фото

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
        "/buy — купить VIP\n\n"
        "💡 <i>Совет: пиши промпты подробно, например:\n"
        "/gen фотореалистичный кот-самурай на фоне горящего города, 8k</i>",
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

    msg = await message.answer("🎨 Генерирую... (бесплатно, до 30 сек)")
    try:
        # Генерация без автоулучшения (работает стабильно)
        image = hf_client.text_to_image(prompt, model=TEXT2IMG_MODEL)
        bio = BytesIO()
        image.save(bio, format="JPEG")
        bio.seek(0)
        await message.reply_photo(
            BufferedInputFile(bio.read(), filename="generated.jpg")
        )
        await msg.delete()
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка: {e}")

@router.message(F.photo)
async def handle_photo(message: types.Message):
    if not await check_access(message):
        return
    prompt = message.caption or "улучшить качество, сделать красиво"
    file_id = message.photo[-1].file_id
    file = await message.bot.get_file(file_id)
    file_url = f"https://api.telegram.org/file/bot{message.bot.token}/{file.file_path}"

    msg = await message.answer("🔧 Обрабатываю фото... (до 40 сек)")
    try:
        # Скачиваем фото
        response = requests.get(file_url)
        image_bytes = response.content

        # Используем image_to_image через клиент (избегаем DNS-ошибок)
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
        await message.reply_photo(
            BufferedInputFile(bio.read(), filename="edited.jpg")
        )
        await msg.delete()
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка: {e}")

# ==================== АДМИН-ПАНЕЛЬ ====================
def admin_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="➕ Выдать VIP", callback_data="admin_give_vip")],
        [InlineKeyboardButton(text="➖ Снять VIP", callback_data="admin_remove_vip")],
        [InlineKeyboardButton(text="📋 Список VIP", callback_data="admin_list_vip")],
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="admin_refresh")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@router.message(Command("admin"))
async def admin_panel(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer(
        "🛡 <b>Админ-панель ☂️ ixxy AI</b>",
        reply_markup=admin_keyboard(),
        parse_mode=ParseMode.HTML
    )

@router.callback_query(F.data.startswith("admin_"))
async def admin_callback(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    action = callback.data

    if action == "admin_stats":
        vips = load_vips()
        free_data = load_free_usage()
        text = (
            f"📊 <b>Статистика</b>\n"
            f"└ Пользователей с бесплатными попытками: {len(free_data)}\n"
            f"└ VIP-пользователей: {len(vips)}\n"
        )
        await callback.message.edit_text(text, reply_markup=admin_keyboard(), parse_mode=ParseMode.HTML)
        await callback.answer()

    elif action == "admin_list_vip":
        vips = load_vips()
        text = "<b>📋 Список VIP:</b>\n"
        if vips:
            for uid in vips:
                text += f"• <code>{uid}</code>\n"
        else:
            text += "• никого"
        await callback.message.edit_text(text, reply_markup=admin_keyboard(), parse_mode=ParseMode.HTML)
        await callback.answer()

    elif action == "admin_give_vip":
        await state.set_state(AdminActions.waiting_for_vip_id)
        await callback.message.edit_text(
            "➕ Введите <b>ID пользователя</b>, которому выдать VIP:",
            parse_mode=ParseMode.HTML
        )
        await callback.answer()

    elif action == "admin_remove_vip":
        await state.set_state(AdminActions.waiting_for_remove_vip_id)
        await callback.message.edit_text(
            "➖ Введите <b>ID пользователя</b>, у которого забрать VIP:",
            parse_mode=ParseMode.HTML
        )
        await callback.answer()

    elif action == "admin_refresh":
        await callback.message.edit_text(
            "🛡 <b>Админ-панель ☂️ ixxy AI</b>",
            reply_markup=admin_keyboard(),
            parse_mode=ParseMode.HTML
        )
        await callback.answer()

@router.message(StateFilter(AdminActions.waiting_for_vip_id))
async def process_give_vip_id(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Введите числовой ID.")
        return
    uid = int(message.text)
    if is_vip(uid):
        await message.answer(f"ℹ️ Пользователь {uid} уже VIP.")
    else:
        add_vip(uid)
        await message.answer(f"✅ Пользователь {uid} теперь VIP!")
        try:
            await message.bot.send_message(uid, "🎉 Тебе выдали вечный VIP! Используй /gen и /edit без ограничений.")
        except:
            pass
    await state.clear()
    await message.answer("🛡 Админ-панель:", reply_markup=admin_keyboard())

@router.message(StateFilter(AdminActions.waiting_for_remove_vip_id))
async def process_remove_vip_id(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Введите числовой ID.")
        return
    uid = int(message.text)
    vips = load_vips()
    if uid not in vips:
        await message.answer(f"ℹ️ Пользователь {uid} не VIP.")
    else:
        vips.remove(uid)
        save_vips(vips)
        await message.answer(f"❌ Пользователь {uid} лишён VIP.")
    await state.clear()
    await message.answer("🛡 Админ-панель:", reply_markup=admin_keyboard())