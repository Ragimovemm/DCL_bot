import asyncio
import os
import logging
from datetime import datetime, timedelta
from typing import Set, Dict
from aiohttp import web
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import (
    Message,
    KeyboardButton,
    ReplyKeyboardMarkup,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    CallbackQuery
)
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart, BaseFilter
from aiogram.client.default import DefaultBotProperties
from dotenv import load_dotenv

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log")
    ]
)
logger = logging.getLogger(__name__)

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")

ADMINS = set(map(int, os.getenv("ADMINS", "").split(','))) if os.getenv("ADMINS") else set()
RESTRICTED_USERS: Set[int] = set()

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
router = Router()
dp.include_router(router)

# Хранение данных
user_work_modes: Dict[int, Dict[str, str]] = {}
user_names: Dict[int, str] = {}
awaiting_name_input: Set[int] = set()

# ИЗМЕНЕНИЕ: комментарии теперь для каждого пользователя и даты
user_comments: Dict[int, Dict[str, str]] = {}  # {user_id: {date_str: comment}}
awaiting_comment_input: Dict[int, str] = {}  # {user_id: date_str}

# Новый словарь статусов и эмодзи
status_icons = {
    "Выходной": "🛌",
    "Отпуск": "🏝️",
    "Офис": "🏢",
    "Дистанционно": "🏠",
    "Командировка": "✈️",
    "Больничный": "🩺"
}

class IsAdminFilter(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        return message.from_user.id in ADMINS

class IsNotRestrictedFilter(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        return message.from_user.id not in RESTRICTED_USERS

# Фильтры
dp.message.filter(IsNotRestrictedFilter())
router.message.filter(IsNotRestrictedFilter())

def get_main_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(text="🧑‍💼 Мое расписание")],
        [KeyboardButton(text="✏️ Изменить имя")],
    ]
    if user_id in ADMINS:
        buttons.extend([
            [KeyboardButton(text="👥 Расписание коллег")],
            [KeyboardButton(text="⚙️ Управление доступом")]
        ])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

# ИЗМЕНЕНИЕ: кнопки комментариев теперь для каждой даты
def build_schedule_keyboard(user_id: int) -> InlineKeyboardMarkup:
    today = datetime.now().date()
    buttons = []
    for i in range(10):
        day = today + timedelta(days=i)
        date_str = day.isoformat()
        is_weekend = day.weekday() >= 5

        if user_id not in user_work_modes:
            user_work_modes[user_id] = {}

        status = user_work_modes[user_id].get(date_str)
        if status is None:
            status = "Выходной" if is_weekend else "Офис"
            user_work_modes[user_id][date_str] = status

        icon = status_icons.get(status, "🏢")

        day_name = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][day.weekday()]
        btn_text = f"{icon} {day.strftime('%d.%m')} ({day_name})"

        if is_weekend:
            callback_data = f"toggle_weekend_{date_str}"
        else:
            callback_data = f"toggle_{date_str}"

        # Кнопка для комментария на конкретный день
        comment_for_day = user_comments.get(user_id, {}).get(date_str)
        if comment_for_day:
            comment_btn = InlineKeyboardButton(
                text="🗑️ Удалить комментарий", callback_data=f"delete_comment_{date_str}"
            )
        else:
            comment_btn = InlineKeyboardButton(
                text="💬 Добавить комментарий", callback_data=f"add_comment_{date_str}"
            )

        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=callback_data), comment_btn])

    return InlineKeyboardMarkup(inline_keyboard=buttons)

@dp.message(CommandStart())
async def start(message: Message):
    user_id = message.from_user.id
    if user_id in RESTRICTED_USERS:
        await message.answer("⛔ Ваш доступ к боту ограничен администратором")
        return

    user_names[user_id] = message.from_user.full_name

    greeting_text = (
        "👋 Привет! Этот бот помогает управлять вашим рабочим расписанием.\n\n"
        "Вот что означают эмодзи статусов:\n"
        "🛌 Выходной\n"
        "🏝️ Отпуск\n"
        "🏢 Офис\n"
        "🏠 Дистанционно\n"
        "✈️ Командировка\n"
        "🩺 Больничный\n\n"
        "Выберите действие ниже:"
    )

    await message.answer(greeting_text, reply_markup=get_main_keyboard(user_id))

@dp.message(F.text == "✏️ Изменить имя")
async def change_name_start(message: Message):
    user_id = message.from_user.id
    if user_id in RESTRICTED_USERS:
        await message.answer("⛔ Ваш доступ к боту ограничен администратором")
        return
    awaiting_name_input.add(user_id)
    await message.answer("✏️ Введите новое имя для отображения:")

@dp.message(lambda message: message.from_user.id in awaiting_name_input)
async def save_new_name(message: Message):
    user_id = message.from_user.id
    new_name = message.text.strip()
    if not new_name:
        await message.answer("❌ Имя не может быть пустым. Попробуйте ещё раз.")
        return
    if len(new_name) > 50:
        await message.answer("❌ Имя слишком длинное. Максимум 50 символов.")
        return
    user_names[user_id] = new_name
    awaiting_name_input.discard(user_id)
    await message.answer(f"✅ Имя успешно обновлено на: {new_name}", reply_markup=get_main_keyboard(user_id))

@dp.message(F.text == "🧑‍💼 Мое расписание")
async def my_schedule(message: Message):
    user_id = message.from_user.id
    kb = build_schedule_keyboard(user_id)
    await message.answer("📅 Ваше расписание на 10 дней:", reply_markup=kb)
    today = datetime.now().date()
    comment = user_comments.get(user_id, {}).get(today.isoformat())
    if comment:
        await message.answer(f"💬 Ваш комментарий на сегодня:\n\n{comment}")

@dp.callback_query(lambda c: c.data.startswith("toggle_") and not c.data.startswith("toggle_weekend_"))
async def toggle_date(callback: CallbackQuery):
    try:
        user_id = callback.from_user.id
        date_str = callback.data[7:]
        datetime.fromisoformat(date_str)

        current = user_work_modes.get(user_id, {}).get(date_str, "Офис")
        new_status = {
            "Офис": "Дистанционно",
            "Дистанционно": "Командировка",
            "Командировка": "Больничный",
            "Больничный": "Отпуск",
            "Отпуск": "Офис"
        }.get(current, "Офис")

        user_work_modes.setdefault(user_id, {})[date_str] = new_status

        await callback.message.edit_reply_markup(reply_markup=build_schedule_keyboard(user_id))
        await callback.answer(f"Установлен режим: {new_status}")

    except Exception as e:
        logger.error(f"Ошибка переключения даты: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)

@dp.callback_query(F.data.startswith("toggle_weekend_"))
async def toggle_weekend_date(callback: CallbackQuery):
    try:
        user_id = callback.from_user.id
        date_str = callback.data[len("toggle_weekend_"):]
        datetime.fromisoformat(date_str)

        current = user_work_modes.get(user_id, {}).get(date_str, "Выходной")

        # Цикл переключения: Выходной -> Командировка -> Отпуск -> Выходной
        new_status = {
            "Выходной": "Командировка",
            "Командировка": "Отпуск",
            "Отпуск": "Выходной"
        }.get(current, "Выходной")

        user_work_modes.setdefault(user_id, {})[date_str] = new_status

        await callback.message.edit_reply_markup(reply_markup=build_schedule_keyboard(user_id))
        await callback.answer(f"Установлен режим: {new_status}")

    except Exception as e:
        logger.error(f"Ошибка переключения выходного дня: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)

@dp.message(F.text == "👥 Расписание коллег")
async def colleagues_schedule(message: Message):
    try:
        if message.from_user.id not in ADMINS:
            await message.answer("⛔ У вас нет прав доступа к этой функции")
            return

        active_users = {
            uid: name for uid, name in user_names.items()
            if uid != message.from_user.id and uid not in RESTRICTED_USERS
        }
        if not active_users:
            await message.answer("Нет активных пользователей")
            return

        buttons = [
            [InlineKeyboardButton(text="🔎 Выбрать сотрудника", callback_data="select_colleague")],
            [InlineKeyboardButton(text="📊 Общее расписание", callback_data="general_schedule")]
        ]
        await message.answer(
            "Выберите действие:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )
    except Exception as e:
        logger.error(f"Ошибка в colleagues_schedule: {e}")
        await message.answer("Произошла ошибка при загрузке списка коллег")

@dp.callback_query(F.data == "select_colleague")
async def select_colleague(callback: CallbackQuery):
    try:
        active_users = {
            uid: name for uid, name in user_names.items()
            if uid != callback.from_user.id and uid not in RESTRICTED_USERS
        }
        buttons = [
            [InlineKeyboardButton(text=name, callback_data=f"colleague_{uid}")]
            for uid, name in active_users.items()
        ]
        await callback.message.edit_text(
            "Выберите сотрудника:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в select_colleague: {e}")
        await callback.answer("Ошибка загрузки списка", show_alert=True)

@dp.callback_query(F.data == "general_schedule")
async def general_schedule(callback: CallbackQuery):
    try:
        active_users = {
            uid: name for uid, name in user_names.items()
            if uid != callback.from_user.id and uid not in RESTRICTED_USERS
        }
        if not active_users:
            await callback.answer("Нет активных пользователей", show_alert=True)
            return

        today = datetime.now().date()
        dates = [today + timedelta(days=i) for i in range(10)]
        day_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

        text = "📅 Расписание:\n\n"
        for uid, name in active_users.items():
            text += f"• {name}\n"
            user_comments_for_user = user_comments.get(uid, {})
            for d in dates:
                date_str = d.isoformat()
                comment = user_comments_for_user.get(date_str)
                status = user_work_modes.get(uid, {}).get(date_str)
                if status is None:
                    status = "Выходной" if d.weekday() >= 5 else "Офис"
                emoji = status_icons.get(status, "🏢")
                day_name = day_names[d.weekday()]
                text += f"  - {d.strftime('%d.%m')}({day_name}): {emoji}"
                if comment:
                    text += f"  💬 {comment}"
                text += "\n"
            text += "\n"

        await callback.message.answer(text)
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в general_schedule: {e}")
        await callback.answer("Ошибка формирования общего расписания", show_alert=True)

@dp.callback_query(F.data.startswith("colleague_"))
async def show_user_schedule(callback: CallbackQuery):
    try:
        user_id = int(callback.data.split('_')[1])
        name = user_names.get(user_id, "Неизвестный сотрудник")
        user_comments_for_user = user_comments.get(user_id, {})

        text = f"<b>📅 Расписание {name}:</b>\n\n"
        today = datetime.now().date()
        for i in range(10):
            day = today + timedelta(days=i)
            date_str = day.isoformat()
            is_weekend = day.weekday() >= 5
            if is_weekend:
                status = user_work_modes.get(user_id, {}).get(date_str, "Выходной")
            else:
                status = user_work_modes.get(user_id, {}).get(date_str, "Офис")
            icon = status_icons.get(status, "🏢")
            day_name = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][day.weekday()]
            comment = user_comments_for_user.get(date_str)
            text += f"{icon} {day.strftime('%d.%m')} ({day_name})"
            if comment:
                text += f"  💬 {comment}"
            text += "\n"

        await callback.message.answer(text, parse_mode=ParseMode.HTML)
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в show_user_schedule: {e}")
        await callback.answer("Ошибка загрузки расписания", show_alert=True)

# --- Обработчики комментариев ---

@dp.callback_query(F.data.startswith("add_comment_"))
async def add_comment_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    date_str = callback.data[len("add_comment_"):]
    awaiting_comment_input[user_id] = date_str
    await callback.message.answer(f"💬 Введите комментарий на {date_str} (будет виден только администраторам):")
    await callback.answer()

@dp.message(lambda m: m.from_user.id in awaiting_comment_input)
async def save_comment_handler(message: Message):
    user_id = message.from_user.id
    comment = message.text.strip()
    if not comment:
        await message.answer("❌ Комментарий не может быть пустым. Попробуйте ещё раз.")
        return
    date_str = awaiting_comment_input[user_id]
    user_comments.setdefault(user_id, {})[date_str] = comment
    del awaiting_comment_input[user_id]
    await message.answer(f"✅ Ваш комментарий на {date_str} сохранён.", reply_markup=get_main_keyboard(user_id))

@dp.callback_query(F.data.startswith("delete_comment_"))
async def delete_comment_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    date_str = callback.data[len("delete_comment_"):]
    if user_id in user_comments and date_str in user_comments[user_id]:
        del user_comments[user_id][date_str]
        await callback.answer("Комментарий удалён")
        await callback.message.edit_reply_markup(reply_markup=build_schedule_keyboard(user_id))
    else:
        await callback.answer("Комментарий отсутствует", show_alert=True)

# --- Управление доступом ---

@dp.message(F.text == "⚙️ Управление доступом")
async def access_management(message: Message):
    if message.from_user.id not in ADMINS:
        await message.answer("⛔ У вас нет прав доступа к этой функции")
        return

    try:
        buttons = [
            [InlineKeyboardButton(text="⛔ Запретить доступ", callback_data="restrict_access")],
            [InlineKeyboardButton(text="✅ Разрешить доступ", callback_data="allow_access")],
            [InlineKeyboardButton(text="👑 Назначить админа", callback_data="make_admin")],
            [InlineKeyboardButton(text="❌ Снять админа", callback_data="remove_admin")],
            [InlineKeyboardButton(text="📋 Список пользователей", callback_data="list_users")]
        ]
        await message.answer(
            "Управление доступом:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )
    except Exception as e:
        logger.error(f"Ошибка в access_management: {e}")
        await message.answer("Произошла ошибка при загрузке меню управления")

# --- Ограничение доступа и админские команды (без изменений) ---

@dp.callback_query(F.data == "restrict_access")
async def restrict_access_handler(callback: CallbackQuery):
    try:
        available_users = [
            [InlineKeyboardButton(text=user_names.get(uid, str(uid)), callback_data=f"restrict_{uid}")]
            for uid in user_names if uid not in ADMINS and uid not in RESTRICTED_USERS
        ]
        if not available_users:
            await callback.answer("Нет пользователей для ограничения", show_alert=True)
            return

        await callback.message.edit_text(
            "Выберите пользователя для ограничения доступа:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=available_users)
        )
    except Exception as e:
        logger.error(f"Ошибка в restrict_access_handler: {e}")
        await callback.answer("Ошибка обработки", show_alert=True)

@dp.callback_query(F.data.startswith("restrict_"))
async def restrict_user(callback: CallbackQuery):
    try:
        user_id = int(callback.data.split('_')[1])
        RESTRICTED_USERS.add(user_id)
        if user_id in user_comments:
            del user_comments[user_id]
        await callback.message.edit_text(
            f"⛔ Пользователь {user_names.get(user_id, user_id)} теперь без доступа"
        )
        try:
            await bot.send_message(user_id, "⛔ Ваш доступ к боту был ограничен администратором")
        except:
            logger.warning(f"Не удалось уведомить пользователя {user_id}")
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в restrict_user: {e}")
        await callback.answer("Ошибка операции", show_alert=True)

@dp.callback_query(F.data == "allow_access")
async def allow_access_handler(callback: CallbackQuery):
    try:
        if not RESTRICTED_USERS:
            await callback.answer("Нет пользователей с ограниченным доступом", show_alert=True)
            return

        buttons = [
            [InlineKeyboardButton(text=user_names.get(uid, str(uid)), callback_data=f"allow_{uid}")]
            for uid in RESTRICTED_USERS
        ]
        await callback.message.edit_text(
            "Выберите пользователя для восстановления доступа:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )
    except Exception as e:
        logger.error(f"Ошибка в allow_access_handler: {e}")
        await callback.answer("Ошибка обработки", show_alert=True)

@dp.callback_query(F.data.startswith("allow_"))
async def allow_user(callback: CallbackQuery):
    try:
        user_id = int(callback.data.split('_')[1])
        if user_id in RESTRICTED_USERS:
            RESTRICTED_USERS.remove(user_id)
            await callback.message.edit_text(
                f"✅ Пользователь {user_names.get(user_id, user_id)} теперь имеет доступ"
            )
            try:
                await bot.send_message(user_id, "✅ Ваш доступ к боту был восстановлен администратором")
            except:
                logger.warning(f"Не удалось уведомить пользователя {user_id}")
        else:
            await callback.answer("Пользователь не был ограничен", show_alert=True)
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в allow_user: {e}")
        await callback.answer("Ошибка операции", show_alert=True)

@dp.callback_query(F.data == "list_users")
async def list_users_handler(callback: CallbackQuery):
    try:
        user_list = []
        for uid, name in user_names.items():
            status = "👑 Админ" if uid in ADMINS else ("⛔ Ограничен" if uid in RESTRICTED_USERS else "✅ Активен")
            user_list.append(f"{name} (ID: {uid}) — {status}")

        await callback.message.edit_text(
            "Список пользователей:\n\n" + "\n".join(user_list) if user_list else "Нет пользователей"
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в list_users_handler: {e}")
        await callback.answer("Ошибка загрузки списка", show_alert=True)

@dp.callback_query(F.data == "make_admin")
async def make_admin_handler(callback: CallbackQuery):
    try:
        candidates = [
            [InlineKeyboardButton(text=user_names.get(uid, str(uid)), callback_data=f"make_admin_{uid}")]
            for uid in user_names if uid not in ADMINS
        ]

        if not candidates:
            await callback.answer("Все пользователи уже являются администраторами", show_alert=True)
            return

        await callback.message.edit_text(
            "Выберите пользователя для назначения администратором:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=candidates)
        )
    except Exception as e:
        logger.error(f"Ошибка в make_admin_handler: {e}")
        await callback.answer("Ошибка обработки", show_alert=True)

@dp.callback_query(F.data.startswith("make_admin_"))
async def make_admin(callback: CallbackQuery):
    try:
        user_id = int(callback.data.split('_')[2])
        if user_id in ADMINS:
            await callback.answer("Пользователь уже администратор", show_alert=True)
            return

        ADMINS.add(user_id)
        # TODO: сохранить ADMINS на диск при необходимости

        await callback.message.edit_text(
            f"✅ Пользователь {user_names.get(user_id, str(user_id))} назначен администратором"
        )
        try:
            await bot.send_message(user_id, "👑 Вы были назначены администратором бота")
        except Exception:
            logger.warning(f"Не удалось уведомить пользователя {user_id}")
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в make_admin: {e}")
        await callback.answer("Ошибка операции", show_alert=True)

@dp.callback_query(F.data == "remove_admin")
async def remove_admin_handler(callback: CallbackQuery):
    try:
        candidates = [
            [InlineKeyboardButton(text=user_names.get(uid, str(uid)), callback_data=f"remove_admin_{uid}")]
            for uid in ADMINS if uid != callback.from_user.id
        ]

        if not candidates:
            await callback.answer("Нет других администраторов для снятия", show_alert=True)
            return

        await callback.message.edit_text(
            "Выберите администратора для снятия прав:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=candidates)
        )
    except Exception as e:
        logger.error(f"Ошибка в remove_admin_handler: {e}")
        await callback.answer("Ошибка обработки", show_alert=True)

@dp.callback_query(F.data.startswith("remove_admin_"))
async def remove_admin(callback: CallbackQuery):
    try:
        user_id = int(callback.data.split('_')[2])
        if user_id not in ADMINS:
            await callback.answer("Пользователь не является администратором", show_alert=True)
            return

        ADMINS.remove(user_id)
        # TODO: сохранить ADMINS на диск при необходимости

        await callback.message.edit_text(
            f"❌ Пользователь {user_names.get(user_id, str(user_id))} лишён прав администратора"
        )
        try:
            await bot.send_message(user_id, "⚠️ Ваши права администратора были сняты")
        except Exception:
            logger.warning(f"Не удалось уведомить пользователя {user_id}")
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в remove_admin: {e}")
        await callback.answer("Ошибка операции", show_alert=True)

# Веб-сервер
async def handle(request):
    return web.Response(text="✅ Бот работает!")

async def run_web():
    app = web.Application()
    app.router.add_get("/", handle)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()
    logger.info("Веб-сервер запущен на порту 8080")

# Ежедневная очистка комментариев в полночь
async def clear_comments_daily():
    while True:
        now = datetime.now()
        next_midnight = datetime.combine(now.date() + timedelta(days=1), datetime.min.time())
        seconds_until_midnight = (next_midnight - now).total_seconds()
        await asyncio.sleep(seconds_until_midnight)
        user_comments.clear()  # очищаем все комментарии всех пользователей
        logger.info("Комментарии очищены после окончания дня.")

async def main():
    await asyncio.gather(
        dp.start_polling(bot),
        run_web(),
        clear_comments_daily()
    )

if __name__ == "__main__":
    asyncio.run(main())
