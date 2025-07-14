import asyncio
import os
from datetime import datetime, timedelta, time as dtime
from aiohttp import web

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

user_work_modes = {}  # {user_id: {date: "Офис" или "Дистанционно"}}
user_names = {}  # {user_id: full_name}

main_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="🧑‍💼Мое расписание")],
    [KeyboardButton(text="👥Расписание коллег")]
], resize_keyboard=True)

async def ensure_user_name(message: Message):
    user_id = message.from_user.id
    if user_id not in user_names:
        user_names[user_id] = message.from_user.full_name

def build_schedule_keyboard(user_id: int):
    today = datetime.today().date()
    buttons = []
    for i in range(10):
        d = today + timedelta(days=i)
        ds = str(d)
        weekday = d.weekday()
        is_weekend = weekday in [5, 6]
        if is_weekend:
            user_work_modes.setdefault(user_id, {})[ds] = "Выходной"
        elif ds not in user_work_modes.setdefault(user_id, {}):
            user_work_modes[user_id][ds] = "Офис"
        current = user_work_modes[user_id][ds]
        symbol = "🏝️" if is_weekend else ("🏢" if current == "Офис" else "🏠")
        text = f"{symbol} {d.strftime('%d.%m')} ({d.strftime('%a').replace('Mon','Пн').replace('Tue','Вт').replace('Wed','Ср').replace('Thu','Чт').replace('Fri','Пт').replace('Sat','Сб').replace('Sun','Вс')})"
        callback = f"toggle_{ds}" if not is_weekend else "noop"
        buttons.append([InlineKeyboardButton(text=text, callback_data=callback)])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@dp.message(CommandStart())
async def start(message: Message):
    await ensure_user_name(message)
    await message.answer(f"👋 Привет, {message.from_user.full_name}! Выбери действие:", reply_markup=main_kb)

@dp.message(F.text == "🧑‍💼Мое расписание")
async def choose_work_days(message: Message):
    await ensure_user_name(message)
    kb = build_schedule_keyboard(message.from_user.id)
    await message.answer("🔎 Формат на 10 дней:", reply_markup=kb)

@dp.callback_query(F.data.startswith("toggle_"))
async def toggle_format(callback: CallbackQuery):
    user_id = callback.from_user.id
    date = callback.data.replace("toggle_", "")
    d = datetime.strptime(date, "%Y-%m-%d").date()
    if d.weekday() in [5, 6]:
        return await callback.answer("Выходной. Формат не изменяется.", show_alert=True)
    current = user_work_modes.setdefault(user_id, {}).get(date, "Офис")
    user_work_modes[user_id][date] = "Дистанционно" if current == "Офис" else "Офис"

    kb = build_schedule_keyboard(user_id)
    await callback.message.edit_text("🔎 Формат на 10 дней:", reply_markup=kb)
    await callback.answer("Обновлено")

@dp.callback_query(F.data == "noop")
async def ignore_weekend(callback: CallbackQuery):
    await callback.answer("Это выходной. Формат не меняется.", show_alert=True)

@dp.message(F.text == "👥Расписание коллег")
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
    days = user_work_modes.setdefault(uid, {})

    text = f"<b>Формат работы: {name}</b>\n"
    for i in range(10):
        d = datetime.today().date() + timedelta(days=i)
        ds = str(d)
        weekday = d.strftime('%a').replace('Mon','Пн').replace('Tue','Вт').replace('Wed','Ср').replace('Thu','Чт').replace('Fri','Пт').replace('Sat','Сб').replace('Sun','Вс')
        is_weekend = d.weekday() in [5,6]
        if is_weekend:
            format_type = "Выходной"
        else:
            format_type = days.get(ds, "Офис")
        symbol = "🏝️" if is_weekend else ("🏢" if format_type == "Офис" else "🏠")
        label = "Выходной" if is_weekend else format_type
        text += f"{symbol} {d.strftime('%d.%m')} ({weekday}): {label}\n"

    await callback.message.edit_text(text)
    await callback.answer()

async def handle(request):
    return web.Response(text="✅ Бот работает!")

app = web.Application()
app.add_routes([web.get("/", handle)])

async def run_web():
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()

async def main():
    await asyncio.gather(
        dp.start_polling(bot),
        run_web()
    )

if __name__ == "__main__":
    asyncio.run(main())
