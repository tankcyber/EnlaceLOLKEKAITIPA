import asyncio
import aiohttp
import json
import os
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.client.bot import DefaultBotProperties

# ========== КОНФИГУРАЦИЯ ==========

GROQ_API_KEY = "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"

# ========== ВЛАДЕЛЕЦ БОТА (ID из Telegram) ==========
OWNER_ID = 5439940299  # 🔥 ВСТАВЬ СВОЙ ID СЮДА! (число, не username)

# Цена подписки в звёздах
STAR_PRICE = 30

# Файл для хранения данных пользователей
DATA_FILE = "users_data.json"

# Модели
FREE_MODELS = {
    "llama-3.3-70b-versatile": "🦙 Llama 70B",
    "llama-3.1-8b-instant": "⚡ Llama 8B"
}

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

# Инициализация бота
bot = Bot(
    token="8666211095:AAGk41YRGTBIaezj5MzKQ1eFTIMVV8YIiqM",
    default=DefaultBotProperties(parse_mode="Markdown")
)

dp = Dispatcher(storage=MemoryStorage())
user_models = {}

# ========== РАБОТА С ДАННЫМИ ПОЛЬЗОВАТЕЛЕЙ ==========

def load_users_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_users_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_user_data(user_id: int) -> dict:
    data = load_users_data()
    user_id_str = str(user_id)
    if user_id_str not in data:
        data[user_id_str] = {
            "requests_today": 0,
            "last_reset": datetime.now().strftime("%Y-%m-%d"),
            "subscription_until": None,
            "username": None
        }
        save_users_data(data)
    return data[user_id_str]

def update_user_data(user_id: int, updates: dict):
    data = load_users_data()
    user_id_str = str(user_id)
    if user_id_str not in data:
        data[user_id_str] = {
            "requests_today": 0,
            "last_reset": datetime.now().strftime("%Y-%m-%d"),
            "subscription_until": None,
            "username": None
        }
    data[user_id_str].update(updates)
    save_users_data(data)

def reset_daily_requests(user_id: int):
    user_data = get_user_data(user_id)
    today = datetime.now().strftime("%Y-%m-%d")
    
    if user_data["last_reset"] != today:
        user_data["requests_today"] = 0
        user_data["last_reset"] = today
        update_user_data(user_id, {
            "requests_today": 0,
            "last_reset": today
        })
        return True
    return False

def can_make_request(user_id: int) -> tuple:
    user_data = get_user_data(user_id)
    reset_daily_requests(user_id)
    
    subscription_until = user_data.get("subscription_until")
    if subscription_until:
        expiry_date = datetime.strptime(subscription_until, "%Y-%m-%d")
        if expiry_date > datetime.now():
            return True, None
    
    if user_data["requests_today"] >= 5:
        return False, "⏰ *Лимит 5 бесплатных запросов в день исчерпан!*\n\n" \
                      f"💎 Оформи подписку за {STAR_PRICE} звёзд в месяц:\n" \
                      f"👤 Напиши владельцу @SedoyDiada"
    
    return True, None

def increment_request(user_id: int):
    user_data = get_user_data(user_id)
    reset_daily_requests(user_id)
    new_count = user_data["requests_today"] + 1
    update_user_data(user_id, {"requests_today": new_count})

def has_active_subscription(user_id: int) -> bool:
    user_data = get_user_data(user_id)
    subscription_until = user_data.get("subscription_until")
    if subscription_until:
        expiry_date = datetime.strptime(subscription_until, "%Y-%m-%d")
        return expiry_date > datetime.now()
    return False

def get_remaining_free_requests(user_id: int) -> int:
    user_data = get_user_data(user_id)
    reset_daily_requests(user_id)
    return max(0, 5 - user_data["requests_today"])

def is_owner(user_id: int) -> bool:
    """Проверяет, является ли пользователь владельцем"""
    return user_id == OWNER_ID

# ========== КЛАВИАТУРЫ ==========

def get_main_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    remaining = get_remaining_free_requests(user_id)
    has_sub = has_active_subscription(user_id)
    
    if has_sub:
        status_text = "💎 Премиум"
    else:
        status_text = f"🎫 Бесплатно: {remaining}/5"
    
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=f"📊 Статус | {status_text}")],
            [KeyboardButton(text="🧠 Сменить модель"), KeyboardButton(text="💎 Купить подписку")],
            [KeyboardButton(text="ℹ️ О боте"), KeyboardButton(text="🔄 Сбросить диалог")]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )
    return keyboard

def model_choice_keyboard():
    buttons = []
    for model_id, model_name in FREE_MODELS.items():
        buttons.append([InlineKeyboardButton(text=model_name, callback_data=f"model_{model_id}")])
    buttons.append([InlineKeyboardButton(text="❌ Закрыть", callback_data="close")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def admin_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👑 Выдать подписку", callback_data="admin_give_sub")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="❌ Закрыть", callback_data="close")]
    ])
    return keyboard

# ========== СОСТОЯНИЯ ==========

class ChatState(StatesGroup):
    waiting_for_question = State()
    admin_waiting_for_user = State()

# ========== ЗАПРОС К GROQ ==========

async def ask_groq(question: str, model: str) -> str:
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    
    if len(question) > 1500:
        question = question[:1500] + "\n\n[сообщение обрезано]"
    
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": question}],
        "temperature": 0.7,
        "max_tokens": 500
    }
    
    timeout = aiohttp.ClientTimeout(total=45, connect=10, sock_read=30)
    
    async with aiohttp.ClientSession(timeout=timeout) as session:
        try:
            async with session.post(GROQ_API_URL, headers=headers, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    answer = data["choices"][0]["message"]["content"]
                    if len(answer) > 3000:
                        answer = answer[:3000] + "\n\n[Ответ обрезан]"
                    return answer
                elif resp.status == 401:
                    return "❌ Неверный API ключ"
                elif resp.status == 429:
                    return "⏳ Лимит запросов. Подожди 30 секунд."
                else:
                    return f"❌ Ошибка API: {resp.status}"
        except asyncio.TimeoutError:
            return "⏰ Превышено время ожидания. Попробуй ещё раз."
        except Exception as e:
            return f"⚠️ Ошибка: {str(e)}"

# ========== ОБРАБОТЧИКИ ==========

@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    user_models[message.from_user.id] = "llama-3.1-8b-instant"
    
    username = message.from_user.username
    if username:
        update_user_data(message.from_user.id, {"username": username})
    
    remaining = get_remaining_free_requests(message.from_user.id)
    has_sub = has_active_subscription(message.from_user.id)
    
    if has_sub:
        sub_until = get_user_data(message.from_user.id).get("subscription_until")
        welcome_msg = f"🌟 *Добро пожаловать!*\n\nУ тебя активна подписка до `{sub_until}`\n\nПросто напиши вопрос."
    else:
        welcome_msg = f"🌟 *Добро пожаловать!*\n\nУ тебя {remaining}/5 бесплатных запросов в день.\n\n💎 Оформи подписку за {STAR_PRICE} звёзд в месяц для неограниченного доступа.\n\nПросто напиши вопрос."
    
    await message.answer(
        welcome_msg,
        reply_markup=get_main_keyboard(message.from_user.id),
        parse_mode="Markdown"
    )
    await state.set_state(ChatState.waiting_for_question)

@dp.message(lambda message: message.text and message.text.startswith("📊 Статус"))
async def status_button(message: Message):
    user_id = message.from_user.id
    remaining = get_remaining_free_requests(user_id)
    has_sub = has_active_subscription(user_id)
    
    if has_sub:
        sub_until = get_user_data(user_id).get("subscription_until")
        status_text = f"💎 *Премиум подписка*\nАктивна до: `{sub_until}`\n\n✅ Неограниченные запросы"
    else:
        status_text = f"🎫 *Бесплатный тариф*\nОсталось запросов сегодня: {remaining}/5\n\n💎 Купи подписку за {STAR_PRICE} звёзд"
    
    await message.answer(
        status_text,
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(user_id)
    )

@dp.message(lambda message: message.text == "💎 Купить подписку")
async def buy_subscription_button(message: Message):
    await message.answer(
        f"💎 *Оформление подписки*\n\n"
        f"💰 Цена: {STAR_PRICE} звёзд\n"
        f"📅 Срок: 1 месяц\n"
        f"✅ Безлимитные запросы\n\n"
        f"🔹 *Как купить:*\n"
        f"1. Отправь {STAR_PRICE} звёзд подарком\n"
        f"2. Напиши @SedoyDiada с чеком\n"
        f"3. Получи подписку в течение 24 часов\n\n"
        f"👤 Владелец: @SedoyDiada",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(message.from_user.id)
    )

@dp.message(lambda message: message.text == "🧠 Сменить модель")
async def change_model_button(message: Message):
    await message.answer(
        "🧠 *Выбери модель:*",
        reply_markup=model_choice_keyboard(),
        parse_mode="Markdown"
    )

@dp.message(lambda message: message.text == "ℹ️ О боте")
async def info_button(message: Message):
    await message.answer(
        "🤖 *О боте*\n\n"
        "Использует Groq API\n\n"
        f"💰 *Тарифы:*\n"
        f"• Бесплатно: 5 запросов/день\n"
        f"• Премиум: {STAR_PRICE} звёзд/месяц\n\n"
        f"👤 Владелец: @SedoyDiada",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(message.from_user.id)
    )

@dp.message(lambda message: message.text == "🔄 Сбросить диалог")
async def reset_button(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(ChatState.waiting_for_question)
    await message.answer(
        "🔄 *Диалог сброшен!*",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(message.from_user.id)
    )

@dp.callback_query(lambda c: c.data.startswith("model_"))
async def process_model_choice(callback: CallbackQuery):
    model_id = callback.data.replace("model_", "")
    user_models[callback.from_user.id] = model_id
    model_name = FREE_MODELS.get(model_id, "Неизвестно")
    
    await callback.message.edit_text(
        f"✅ *Модель изменена!*\n\nТеперь используется: `{model_name}`",
        parse_mode="Markdown"
    )
    await callback.message.answer(
        "✨ Готов к работе!",
        reply_markup=get_main_keyboard(callback.from_user.id)
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "close")
async def close_callback(callback: CallbackQuery):
    await callback.message.delete()
    await callback.answer()

# ========== АДМИН-КОМАНДЫ (ПО ID ВЛАДЕЛЬЦА) ==========

@dp.message(Command("admin"))
async def admin_panel(message: Message):
    """Админ панель (только для владельца по ID)"""
    if not is_owner(message.from_user.id):
        await message.answer("⛔ Доступ запрещён. Ты не являешься владельцем бота.")
        return
    
    await message.answer(
        "👑 *Админ панель*\n\n"
        "Выбери действие:",
        reply_markup=admin_keyboard(),
        parse_mode="Markdown"
    )

@dp.callback_query(lambda c: c.data == "admin_give_sub")
async def admin_give_sub_prompt(callback: CallbackQuery, state: FSMContext):
    """Запрос на ввод username или ID пользователя"""
    if not is_owner(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён")
        return
    
    await callback.message.edit_text(
        "👑 *Выдача подписки*\n\n"
        "Отправь username пользователя (без @) или его ID:\n"
        "Пример: `SedoyDiada` или `123456789`\n\n"
        "Для отмены отправь /cancel",
        parse_mode="Markdown"
    )
    await state.set_state(ChatState.admin_waiting_for_user)
    await callback.answer()

@dp.message(ChatState.admin_waiting_for_user)
async def admin_give_sub_process(message: Message, state: FSMContext):
    """Обработка ввода пользователя для выдачи подписки"""
    if not is_owner(message.from_user.id):
        await message.answer("⛔ Доступ запрещён")
        await state.clear()
        return
    
    user_input = message.text.strip()
    
    # Пытаемся найти пользователя
    target_user_id = None
    target_username = None
    
    # Проверяем, может это числовой ID
    if user_input.isdigit():
        target_user_id = int(user_input)
    else:
        # Это username, ищем по всем пользователям
        target_username = user_input.replace("@", "").lower()
        users_data = load_users_data()
        for uid, data in users_data.items():
            saved_username = data.get("username")
            if saved_username and saved_username.lower() == target_username:
                target_user_id = int(uid)
                break
    
    if not target_user_id:
        await message.answer(
            f"❌ Пользователь `{user_input}` не найден в базе.\n"
            f"Пользователь должен хотя бы раз запустить бота командой /start",
            parse_mode="Markdown"
        )
        await state.clear()
        return
    
    # Выдаём подписку на 30 дней
    expiry_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    update_user_data(target_user_id, {"subscription_until": expiry_date})
    
    # Получаем данные для красивого вывода
    user_data = get_user_data(target_user_id)
    display_name = user_data.get("username") or str(target_user_id)
    
    await message.answer(
        f"✅ *Подписка выдана!*\n\n"
        f"Пользователь: `{display_name}`\n"
        f"ID: `{target_user_id}`\n"
        f"Активна до: `{expiry_date}`",
        parse_mode="Markdown"
    )
    
    # Уведомляем пользователя о выдаче подписки
    try:
        await bot.send_message(
            target_user_id,
            f"🎉 *Поздравляем!*\n\n"
            f"Вам выдана премиум подписка до `{expiry_date}`\n\n"
            f"Теперь у вас неограниченное количество запросов!",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard(target_user_id)
        )
    except Exception as e:
        await message.answer(f"⚠️ Не удалось уведомить пользователя: {e}")
    
    await state.clear()

@dp.callback_query(lambda c: c.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    """Статистика бота"""
    if not is_owner(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён")
        return
    
    users_data = load_users_data()
    total_users = len(users_data)
    active_subs = 0
    total_requests_today = 0
    
    today = datetime.now().strftime("%Y-%m-%d")
    
    for uid, data in users_data.items():
        if data.get("subscription_until"):
            expiry = datetime.strptime(data["subscription_until"], "%Y-%m-%d")
            if expiry > datetime.now():
                active_subs += 1
        
        if data.get("last_reset") == today:
            total_requests_today += data.get("requests_today", 0)
    
    stats_text = (
        f"📊 *Статистика бота*\n\n"
        f"👥 Всего пользователей: {total_users}\n"
        f"💎 Активных подписок: {active_subs}\n"
        f"📝 Запросов сегодня: {total_requests_today}\n"
        f"📅 Данные на: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
    )
    
    await callback.message.edit_text(stats_text, parse_mode="Markdown")
    await callback.answer()

@dp.message(Command("cancel"))
async def cancel_admin(message: Message, state: FSMContext):
    """Отмена админ-действия"""
    if not is_owner(message.from_user.id):
        await message.answer("⛔ Доступ запрещён")
        return
    await state.clear()
    await message.answer("❌ Действие отменено")

# ========== ОБРАБОТКА ВОПРОСОВ ==========

@dp.message(ChatState.waiting_for_question)
async def handle_question(message: Message, state: FSMContext):
    question = message.text.strip()
    
    # Игнорируем кнопки
    buttons = ["📊 Статус", "🧠 Сменить модель", "💎 Купить подписку", "ℹ️ О боте", "🔄 Сбросить диалог"]
    is_button = False
    for btn in buttons:
        if question == btn or question.startswith("📊 Статус"):
            is_button = True
            break
    
    if is_button:
        return
    
    if not question:
        return
    
    # ПРОВЕРКА: может ли пользователь сделать запрос
    can_request, error_msg = can_make_request(message.from_user.id)
    
    if not can_request:
        await message.answer(
            error_msg,
            parse_mode="Markdown",
            reply_markup=get_main_keyboard(message.from_user.id)
        )
        return
    
    if len(question) > 1500:
        await message.answer(
            f"⚠️ *Слишком длинный запрос* ({len(question)} символов)\n\nСократи до 1500 символов.",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard(message.from_user.id)
        )
        return
    
    # Увеличиваем счётчик запросов (если нет подписки)
    if not has_active_subscription(message.from_user.id):
        increment_request(message.from_user.id)
    
    await bot.send_chat_action(message.chat.id, "typing")
    
    thinking_msg = await message.answer("🤔 *Думаю...*", parse_mode="Markdown")
    
    model = user_models.get(message.from_user.id, "llama-3.1-8b-instant")
    model_name = FREE_MODELS.get(model, "Неизвестно")
    
    try:
        answer = await asyncio.wait_for(ask_groq(question, model), timeout=50)
    except asyncio.TimeoutError:
        answer = "⏰ Превышено время ожидания. Попробуй ещё раз."
    
    await thinking_msg.delete()
    
    await message.answer(
        f"{answer}\n\n— {model_name}",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(message.from_user.id)
    )
    
    # Если осталось мало бесплатных запросов, напоминаем
    if not has_active_subscription(message.from_user.id):
        remaining = get_remaining_free_requests(message.from_user.id)
        if remaining <= 2 and remaining > 0:
            await message.answer(
                f"⚠️ У вас осталось {remaining} бесплатных запросов на сегодня.\n"
                f"Купи подписку за {STAR_PRICE} звёзд для безлимита — @SedoyDiada",
                parse_mode="Markdown"
            )

# ========== ЗАПУСК ==========

async def main():
    print("🚀 Бот с платной подпиской запущен...")
    print(f"👑 ID владельца: {OWNER_ID}")
    print(f"💰 Цена подписки: {STAR_PRICE} звёзд/месяц")
    print("✅ Готов к работе!")
    
    if OWNER_ID == 123456789:
        print("⚠️ ВНИМАНИЕ! Ты не поменял OWNER_ID на свой!")
        print("⚠️ Вставь свой Telegram ID в переменную OWNER_ID")
    
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump({}, f)
        print("📁 Создан файл users_data.json")
    
    max_retries = 10
    retry_delay = 5
    
    for attempt in range(max_retries):
        try:
            await dp.start_polling(bot)
            break
        except Exception as e:
            print(f"❌ Ошибка (попытка {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                print(f"🔄 Повтор через {retry_delay} сек...")
                await asyncio.sleep(retry_delay)
            else:
                print("❌ Не удалось подключиться")
                raise

if __name__ == "__main__":
    asyncio.run(main())
