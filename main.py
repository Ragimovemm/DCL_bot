import asyncio
import os
from datetime import datetime, timedelta, time as dtime

from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import Message, KeyboardButton, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.client.default import DefaultBotProperties
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
router = Router()
dp.include_router(router)

# Хранилища
bookings = {}  # {date: {time: {"user_id": ..., "duration": ...}}}
user_work_modes = {}  # {user_id: {date: "Офис" или "Дистанционно"}}
user_names = {}  # {user_id: full_name}
temp_booking = {}  # временное хранилище для брони

main_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="📅 Забронировать переговорку")],
    [KeyboardButton(text="🏠 Формат работы")],
    [KeyboardButton(text="📖 Мои брони")],
    [KeyboardButton(text="📋 Все брони"), KeyboardButton(text="👥 Формат работы сотрудников")]
], resize_keyboard=True)

# Вспомогательная функция
async def ensure_user_name(message: Message):
    user_id = message.from_user.id
    if user_id not in user_names:
        user_names[user_id] = message.from_user.full_name

@dp.message(CommandStart())
async def start(message: Message):
    await ensure_user_name(message)
    await message.answer(f"👋 Привет, {message.from_user.full_name}! Выбери действие:", reply_markup=main_kb)

# --- БРОНИРОВАНИЕ ---
@dp.message(F.text == "📅 Забронировать переговорку")
async def start_booking(message: Message):
    await ensure_user_name(message)
    user_id = message.from_user.id
    temp_booking[user_id] = {}
    buttons = [[InlineKeyboardButton(text=(datetime.today() + timedelta(days=i)).strftime("%d.%m.%Y"),
                                     callback_data=f"date_{(datetime.today() + timedelta(days=i)).strftime('%Y-%m-%d')}")]
               for i in range(3)]  # уменьшено с 10 до 3 дней
    await message.answer("📆 Выберите дату:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(F.data.startswith("date_"))
async def choose_time(callback: CallbackQuery):
    user_id = callback.from_user.id
    date = callback.data.replace("date_", "")
    temp_booking[user_id]["date"] = date

    base_dt = datetime.combine(datetime.today(), dtime(8, 30))
    times = [(base_dt + timedelta(minutes=30*i)).strftime("%H:%M") for i in range(19)]
    buttons = [[InlineKeyboardButton(text=t, callback_data=f"time_{t}")] for t in times]

    await callback.message.edit_text("⏰ Выберите время начала:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@dp.callback_query(F.data.startswith("time_"))
async def choose_duration(callback: CallbackQuery):
    user_id = callback.from_user.id
    time = callback.data.replace("time_", "")
    temp_booking[user_id]["time"] = time
    buttons = [
        [InlineKeyboardButton(text="30 мин", callback_data="dur_30")],
        [InlineKeyboardButton(text="60 мин", callback_data="dur_60")],
        [InlineKeyboardButton(text="90 мин", callback_data="dur_90")]
    ]
    await callback.message.edit_text("⏳ Выберите длительность:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@dp.callback_query(F.data.startswith("dur_"))
async def confirm_booking(callback: CallbackQuery):
    user_id = callback.from_user.id
    duration = int(callback.data.replace("dur_", ""))
    data = temp_booking.get(user_id, {})
    date = data.get("date")
    time_str = data.get("time")
    if not date or not time_str:
        await callback.answer("Неверные данные", show_alert=True)
        return await callback.message.edit_text("Ошибка: не выбраны дата и время")

    start_dt = datetime.strptime(f"{date} {time_str}", "%Y-%m-%d %H:%M")
    end_dt = start_dt + timedelta(minutes=duration)

    bookings.setdefault(date, {})
    for t, entry in bookings[date].items():
        booked_start = datetime.strptime(f"{date} {t}", "%Y-%m-%d %H:%M")
        booked_end = booked_start + timedelta(minutes=entry['duration'])
        if booked_start < end_dt and start_dt < booked_end:
            await callback.answer("Пересечение!", show_alert=True)
            return await callback.message.edit_text("❌ Пересечение с другой бронью")

    bookings[date][time_str] = {"user_id": user_id, "duration": duration}
    await callback.message.edit_text(f"✅ Бронь создана: {date} в {time_str} на {duration} мин.")
    temp_booking.pop(user_id, None)
    await callback.answer("Готово")

# --- МОИ БРОНИ ---
@dp.message(F.text == "📖 Мои брони")
async def show_my_bookings(message: Message):
    user_id = message.from_user.id
    entries = [(d, t, info["duration"]) for d, day in bookings.items() for t, info in day.items() if info["user_id"] == user_id]
    if not entries:
        return await message.answer("У вас нет активных броней.")
    buttons = [[InlineKeyboardButton(text=f"{d} {t} — {dur} мин", callback_data=f"cancel_{d}_{t}")] for d, t, dur in entries]
    await message.answer("🖊️ Ваши брони:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(F.data.startswith("cancel_"))
async def cancel_booking(callback: CallbackQuery):
    _, d, t = callback.data.split("_")
    user_id = callback.from_user.id
    if bookings.get(d, {}).get(t, {}).get("user_id") == user_id:
        bookings[d].pop(t)
        await callback.message.edit_text("❌ Бронь отменена")
    else:
        await callback.message.edit_text("Невозможно отменить бронь")
    await callback.answer()

# --- ФОРМАТ РАБОТЫ ---
@dp.message(F.text == "🏠 Формат работы")
async def choose_work_days(message: Message):
    user_id = message.from_user.id
    today = datetime.today().date()
    buttons = []
    for i in range(10):  # 10 дней для формата работы
        d = today + timedelta(days=i)
        ds = str(d)
        current = user_work_modes.setdefault(user_id, {}).get(ds, "Офис")
        user_work_modes[user_id][ds] = current  # установить по умолчанию если нет
        symbol = "🏢" if current == "Офис" else "🏠"
        buttons.append([InlineKeyboardButton(text=f"{symbol} {d.strftime('%d.%m.%Y')}", callback_data=f"toggle_{ds}")])
    await message.answer("🔎 Формат на 10 дней:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(F.data.startswith("toggle_"))
async def toggle_format(callback: CallbackQuery):
    user_id = callback.from_user.id
    date = callback.data.replace("toggle_", "")
    current = user_work_modes.setdefault(user_id, {}).get(date, "Офис")
    user_work_modes[user_id][date] = "Дистанционно" if current == "Офис" else "Офис"

    today = datetime.today().date()
    buttons = []
    for i in range(10):
        d = today + timedelta(days=i)
        ds = str(d)
        status = user_work_modes[user_id].get(ds, "Офис")
        symbol = "🏢" if status == "Офис" else "🏠"
        buttons.append([InlineKeyboardButton(text=f"{symbol} {d.strftime('%d.%m.%Y')}", callback_data=f"toggle_{ds}")])

    await callback.message.edit_text("🔎 Формат на 10 дней:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer("Обновлено")

# --- ВСЕ БРОНИ ---
@dp.message(F.text == "📋 Все брони")
async def all_bookings(message: Message):
    if not bookings:
        return await message.answer("Нет активных броней.")
    text = "<b>Все брони:</b>\n"
    for date in sorted(bookings):
        text += f"\n<b>{date}</b>\n"
        for time, info in sorted(bookings[date].items()):
            name = user_names.get(info["user_id"], str(info["user_id"]))
            text += f"— {time} на {info['duration']} мин — {name}\n"
    await message.answer(text)

# --- ФОРМАТ РАБОТЫ СОТРУДНИКОВ ---
@dp.message(F.text == "👥 Формат работы сотрудников")
async def choose_user_format(message: Message):
    if not user_work_modes:
        return await message.answer("Нет данных о сотрудниках.")
    buttons = [[InlineKeyboardButton(text=user_names[uid], callback_data=f"showfmt_{uid}")]
               for uid in user_work_modes if uid in user_names]
    await message.answer("Выберите пользователя:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(F.data.startswith("showfmt_"))
async def show_user_format(callback: CallbackQuery):
    uid = int(callback.data.replace("showfmt_", ""))
    name = user_names.get(uid, str(uid))
    days = user_work_modes.get(uid, {})
    
    text = f"<b>Формат работы: {name}</b>\n"
    for date, format_type in sorted(days.items()):
        symbol = "🏢" if format_type == "Офис" else "🏠"
        text += f"{symbol} {date}: {format_type}\n"
    
    await callback.message.edit_text(text)
    await callback.answer()

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())