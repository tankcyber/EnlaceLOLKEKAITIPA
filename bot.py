import asyncio
import aiohttp
import json
import os
import re
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.client.bot import DefaultBotProperties
from collections import defaultdict
import base64
import subprocess
import tempfile
from typing import Tuple, Optional

# ========== КОНФИГУРАЦИЯ ==========

GROQ_API_KEY = "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"
OWNER_ID = 5439940299
STAR_PRICE = 30  # Цена подписки в звёздах

DATA_FILE = "users_data.json"
HISTORY_FILE = "chat_history.json"
MAX_HISTORY_LENGTH = 15

MODELS = {
    "llama-3.3-70b-versatile": "🦙 Llama 70B (мощная, сложные задачи)",
    "llama-3.1-8b-instant": "⚡ Llama 8B (быстрая, простые вопросы)"
}

DEFAULT_MODEL = "llama-3.3-70b-versatile"
FAST_MODEL = "llama-3.1-8b-instant"

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

bot = Bot(
    token="8857441987:AAH18rhUKO8MvxzJvm0TPlCaxksHrlHycww",
    default=DefaultBotProperties(parse_mode="Markdown")
)

dp = Dispatcher(storage=MemoryStorage())
user_models = {}
chat_histories = defaultdict(list)

# ========== СИСТЕМНЫЙ ПРОМПТ ==========

HYBRID_SYSTEM_PROMPT = """Ты — универсальный AI-ассистент.

ТВОИ ВОЗМОЖНОСТИ:
1. 📚 Общие знания - отвечай на любые вопросы
2. 🧮 Математика - решай уравнения, примеры, производные, интегралы
3. 💻 Программирование - пиши код, объясняй алгоритмы
4. 📝 Перевод - переводи с/на любые языки
5. 📖 Анализ текста - реферируй, пересказывай
6. ✍️ Креатив - пиши стихи, рассказы

ПРАВИЛА:
- Отвечай на русском
- Формулы в LaTeX: $$...$$
- Код в блоках ```language
- Будь полезным и дружелюбным"""

# ========== РАБОТА С ПОДПИСКАМИ ==========

def has_active_subscription(user_id: int) -> bool:
    """Проверяет наличие активной подписки"""
    user_data = get_user_data(user_id)
    subscription_until = user_data.get("subscription_until")
    if subscription_until:
        try:
            expiry_date = datetime.strptime(subscription_until, "%Y-%m-%d")
            return expiry_date > datetime.now()
        except:
            pass
    return False

def get_subscription_end_date(user_id: int) -> Optional[str]:
    """Возвращает дату окончания подписки"""
    user_data = get_user_data(user_id)
    return user_data.get("subscription_until")

def give_subscription(user_id: int, days: int = 30):
    """Выдаёт подписку пользователю"""
    expiry_date = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
    update_user_data(user_id, {"subscription_until": expiry_date})

def remove_subscription(user_id: int):
    """Удаляет подписку"""
    update_user_data(user_id, {"subscription_until": None})

# ========== РАБОТА С ИСТОРИЕЙ ==========

def load_chat_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_chat_history():
    history_dict = dict(chat_histories)
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(history_dict, f, ensure_ascii=False, indent=2)

def get_user_history(user_id: int) -> list:
    user_id_str = str(user_id)
    if user_id_str not in chat_histories:
        chat_histories[user_id_str] = []
    return chat_histories[user_id_str]

def add_to_history(user_id: int, role: str, content: str):
    user_id_str = str(user_id)
    history = get_user_history(user_id)
    if len(history) >= MAX_HISTORY_LENGTH * 2:
        history.pop(0)
    history.append({"role": role, "content": content[:1000]})
    save_chat_history()

def clear_history(user_id: int):
    user_id_str = str(user_id)
    chat_histories[user_id_str] = []
    save_chat_history()

def get_context_messages(user_id: int, max_messages: int = 6) -> list:
    history = get_user_history(user_id)
    return history[-max_messages:] if history else []

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
            "username": None,
            "total_requests": 0,
            "subscription_until": None  # Добавляем поле для подписки
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
            "username": None,
            "total_requests": 0,
            "subscription_until": None
        }
    data[user_id_str].update(updates)
    save_users_data(data)

def reset_daily_requests(user_id: int):
    user_data = get_user_data(user_id)
    today = datetime.now().strftime("%Y-%m-%d")
    if user_data["last_reset"] != today:
        user_data["requests_today"] = 0
        user_data["last_reset"] = today
        update_user_data(user_id, {"requests_today": 0, "last_reset": today})
        return True
    return False

def can_make_request(user_id: int) -> tuple:
    user_data = get_user_data(user_id)
    reset_daily_requests(user_id)
    
    # Если есть активная подписка - безлимит
    if has_active_subscription(user_id):
        return True, None
    
    # Бесплатный лимит - 20 запросов в день
    if user_data["requests_today"] >= 20:
        return False, "⏰ *Лимит 20 бесплатных запросов в день исчерпан!*\n\n💎 Оформи подписку за 30 звёзд в месяц для безлимита.\n\n👤 Напиши @SedoyDiada"
    
    return True, None

def increment_request(user_id: int):
    user_data = get_user_data(user_id)
    reset_daily_requests(user_id)
    new_count = user_data["requests_today"] + 1
    total = user_data.get("total_requests", 0) + 1
    update_user_data(user_id, {"requests_today": new_count, "total_requests": total})

def get_remaining_free_requests(user_id: int) -> int:
    if has_active_subscription(user_id):
        return float('inf')  # Безлимит
    user_data = get_user_data(user_id)
    reset_daily_requests(user_id)
    return max(0, 20 - user_data["requests_today"])

def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID

# ========== OCR ==========

async def extract_text_from_photo(photo_file_id: str) -> str:
    try:
        file = await bot.get_file(photo_file_id)
        file_bytes = await bot.download_file(file.file_path)
        
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp_file:
            tmp_file.write(file_bytes.getvalue())
            tmp_path = tmp_file.name
        
        result = subprocess.run(
            ['tesseract', tmp_path, 'stdout', '-l', 'rus+eng', '--psm', '6'],
            capture_output=True, text=True, timeout=30
        )
        
        os.unlink(tmp_path)
        
        if result.returncode == 0 and result.stdout.strip():
            text = result.stdout.strip()
            # Нормализация дробей и формул
            text = re.sub(r'(\d+)\s*/\s*(\d+)', r'\1/\2', text)
            return text
        return "Текст на фото не обнаружен"
        
    except Exception as e:
        print(f"❌ OCR ошибка: {e}")
        return "Текст на фото не обнаружен"

# ========== ЗАПРОС К GROQ ==========

async def ask_groq(user_id: int, question: str, photo_text: Optional[str] = None) -> Tuple[str, str]:
    task_type = detect_task_type(question)
    
    if task_type['use_fast_model'] and len(question) < 200:
        model = user_models.get(user_id, FAST_MODEL)
    else:
        model = user_models.get(user_id, DEFAULT_MODEL)
    
    full_question = question
    if photo_text and photo_text != "Текст на фото не обнаружен":
        full_question = f"[Текст с фото: {photo_text[:500]}]\n\n{question}"
    
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    
    context = get_context_messages(user_id, max_messages=6)
    
    messages = [
        {"role": "system", "content": HYBRID_SYSTEM_PROMPT}
    ]
    
    for msg in context[-4:]:
        messages.append(msg)
    
    messages.append({"role": "user", "content": full_question})
    
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.6 if not task_type['is_math'] else 0.2,
        "max_tokens": 1200
    }
    
    timeout = aiohttp.ClientTimeout(total=45)
    
    async with aiohttp.ClientSession(timeout=timeout) as session:
        try:
            async with session.post(GROQ_API_URL, headers=headers, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    answer = data["choices"][0]["message"]["content"]
                    if len(answer) > 3500:
                        answer = answer[:3500] + "\n\n[Ответ сокращён...]"
                    return answer, model
                else:
                    return f"❌ Ошибка API: {resp.status}", model
        except asyncio.TimeoutError:
            return "⏰ Время ожидания истекло. Попробуй короче.", model
        except Exception as e:
            return f"⚠️ Ошибка: {str(e)}", model

def detect_task_type(text: str) -> dict:
    text_lower = text.lower()
    math_patterns = [r'[0-9\+\-\*\/\^=√∫∑∂]', r'уравнени[ея]', r'реши', r'найди', r'производн']
    is_math = any(re.search(p, text_lower) for p in math_patterns)
    return {'is_math': is_math, 'use_fast_model': not is_math and len(text) < 100}

def smart_split_text(text: str, max_length: int = 3500) -> list:
    if len(text) <= max_length:
        return [text]
    
    parts = []
    paragraphs = text.split('\n\n')
    current = ""
    
    for para in paragraphs:
        if len(current) + len(para) + 2 <= max_length:
            current += ('\n\n' + para) if current else para
        else:
            if current:
                parts.append(current)
            current = para
    
    if current:
        parts.append(current)
    return parts

# ========== КЛАВИАТУРЫ ==========

def get_main_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    remaining = get_remaining_free_requests(user_id)
    has_sub = has_active_subscription(user_id)
    
    if has_sub:
        status_text = "💎 Премиум (безлимит)"
    else:
        status_text = f"🎫 Осталось: {remaining}/20"
    
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=f"📊 Статус | {status_text}")],
            [KeyboardButton(text="💎 Купить подписку"), KeyboardButton(text="🧠 Выбрать модель")],
            [KeyboardButton(text="🔄 Сбросить диалог"), KeyboardButton(text="❓ Помощь")]
        ],
        resize_keyboard=True
    )
    return keyboard

def model_choice_keyboard():
    buttons = []
    for model_id, model_name in MODELS.items():
        buttons.append([InlineKeyboardButton(text=model_name, callback_data=f"model_{model_id}")])
    buttons.append([InlineKeyboardButton(text="❌ Закрыть", callback_data="close")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👑 Выдать подписку", callback_data="admin_give_sub")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="❌ Закрыть", callback_data="close")]
    ])

def give_sub_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 30 дней", callback_data="sub_30")],
        [InlineKeyboardButton(text="📅 60 дней", callback_data="sub_60")],
        [InlineKeyboardButton(text="📅 90 дней", callback_data="sub_90")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="close")]
    ])

# ========== СОСТОЯНИЯ ==========

class AdminState(StatesGroup):
    waiting_for_user_id = State()

class ChatState(StatesGroup):
    waiting_for_question = State()

# ========== ОБРАБОТЧИКИ ==========

@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    user_id = message.from_user.id
    user_models[user_id] = DEFAULT_MODEL
    
    username = message.from_user.username
    if username:
        update_user_data(user_id, {"username": username})
    
    remaining = get_remaining_free_requests(user_id)
    has_sub = has_active_subscription(user_id)
    
    if has_sub:
        sub_until = get_subscription_end_date(user_id)
        welcome_msg = f"""🌟 *Добро пожаловать в гибридный AI-ассистент!*

💎 *У вас активна премиум-подписка до {sub_until}*

✅ Безлимитные запросы
✅ Распознавание фото
✅ Память диалога

Просто напиши вопрос или отправь фото!"""
    else:
        welcome_msg = f"""🌟 *Добро пожаловать в гибридный AI-ассистент!*

🎁 *Бесплатно:* {remaining}/20 запросов в день

💎 *Премиум за 30 звёзд:*
• Безлимитные запросы
• Распознавание фото
• Память диалога

Просто напиши вопрос или отправь фото!"""
    
    await message.answer(welcome_msg, reply_markup=get_main_keyboard(user_id), parse_mode="Markdown")
    await state.set_state(ChatState.waiting_for_question)

@dp.message(lambda message: message.text and message.text.startswith("📊 Статус"))
async def status_button(message: Message):
    user_id = message.from_user.id
    remaining = get_remaining_free_requests(user_id)
    user_data = get_user_data(user_id)
    total = user_data.get("total_requests", 0)
    has_sub = has_active_subscription(user_id)
    model = user_models.get(user_id, DEFAULT_MODEL)
    model_name = MODELS.get(model, "Неизвестно")[:30]
    
    if has_sub:
        sub_until = get_subscription_end_date(user_id)
        status_text = f"""📊 *Ваша статистика*

💎 *Премиум подписка*
📅 Активна до: {sub_until}
✅ Безлимитные запросы

🧠 *Модель:* {model_name}
📈 *Всего запросов:* {total}

✨ *Доступно:* Всё!"""
    else:
        status_text = f"""📊 *Ваша статистика*

🎫 *Бесплатный тариф*
📝 *Осталось сегодня:* {remaining}/20
📈 *Всего запросов:* {total}

🧠 *Модель:* {model_name}

💎 *Купи подписку за 30 звёзд:*
• Безлимит
• Приоритетная обработка

👤 По вопросам: @SedoyDiada"""
    
    await message.answer(status_text, parse_mode="Markdown", reply_markup=get_main_keyboard(user_id))

@dp.message(lambda message: message.text == "💎 Купить подписку")
async def buy_subscription_button(message: Message):
    await message.answer(
        f"💎 *Премиум подписка*\n\n"
        f"💰 *Цена:* {STAR_PRICE} звёзд\n"
        f"📅 *Срок:* 1 месяц\n"
        f"✅ *Преимущества:*\n"
        f"• Безлимитные запросы\n"
        f"• Распознавание фото\n"
        f"• Память диалога\n"
        f"• Приоритетная обработка\n\n"
        f"🔹 *Как купить:*\n"
        f"1. Отправь {STAR_PRICE} звёзд подарком\n"
        f"2. Напиши @SedoyDiada с чеком\n"
        f"3. Получи подписку в течение 24 часов\n\n"
        f"👤 *Владелец:* @SedoyDiada",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(message.from_user.id)
    )

@dp.message(lambda message: message.text == "🧠 Выбрать модель")
async def change_model_button(message: Message):
    await message.answer(
        "🧠 *Выбери модель AI:*\n\n"
        "🦙 **Llama 70B** — мощная, для сложных задач\n"
        "⚡ **Llama 8B** — быстрая, для простых вопросов",
        reply_markup=model_choice_keyboard(),
        parse_mode="Markdown"
    )

@dp.message(lambda message: message.text == "❓ Помощь")
async def help_button(message: Message):
    help_text = """❓ *Как пользоваться ботом*

📝 *Просто напиши вопрос* — я отвечу

📸 *Фото с задачами:*
Отправь фото с вопросом в подписи

🔢 *Математика:*
x² - 5x + 6 = 0
Найди производную x³+2x²

💻 *Программирование:*
Напиши функцию на Python

📖 *Текст:*
Переведи на английский, сделай пересказ

🎁 *Тарифы:*
• Бесплатно: 20 запросов/день
• Премиум: 30⭐/месяц — безлимит

👤 Владелец: @SedoyDiada"""
    
    await message.answer(help_text, parse_mode="Markdown", reply_markup=get_main_keyboard(message.from_user.id))

@dp.message(lambda message: message.text == "🔄 Сбросить диалог")
async def reset_button(message: Message, state: FSMContext):
    clear_history(message.from_user.id)
    await state.clear()
    await state.set_state(ChatState.waiting_for_question)
    await message.answer(
        "🔄 *Диалог сброшен!*\n\nИстория удалена.",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(message.from_user.id)
    )

@dp.callback_query(lambda c: c.data.startswith("model_"))
async def process_model_choice(callback: CallbackQuery):
    model_id = callback.data.replace("model_", "")
    user_models[callback.from_user.id] = model_id
    model_name = MODELS.get(model_id, "Неизвестно")
    
    await callback.message.edit_text(f"✅ *Модель изменена на {model_name}*", parse_mode="Markdown")
    await callback.message.answer("✨ Готов к работе!", reply_markup=get_main_keyboard(callback.from_user.id))
    await callback.answer()

@dp.callback_query(lambda c: c.data == "close")
async def close_callback(callback: CallbackQuery):
    await callback.message.delete()
    await callback.answer()

# ========== АДМИН-КОМАНДЫ (ВАЖНО: СТАВИМ ВЫШЕ ОБЫЧНЫХ ОБРАБОТЧИКОВ) ==========

@dp.message(Command("admin"))
async def admin_panel(message: Message):
    """Админ панель - только для владельца"""
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
    """Запрос ID пользователя для выдачи подписки"""
    if not is_owner(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён")
        return
    
    await callback.message.edit_text(
        "👑 *Выдача подписки*\n\n"
        "Отправь ID пользователя или username (без @):\n"
        "Пример: `5439940299` или `SedoyDiada`\n\n"
        "Для отмены отправь /cancel",
        parse_mode="Markdown"
    )
    await state.set_state(AdminState.waiting_for_user_id)
    await callback.answer()

@dp.message(AdminState.waiting_for_user_id)
async def admin_give_sub_process(message: Message, state: FSMContext):
    """Обработка ввода пользователя для выдачи подписки"""
    if not is_owner(message.from_user.id):
        await message.answer("⛔ Доступ запрещён")
        await state.clear()
        return
    
    user_input = message.text.strip()
    target_user_id = None
    
    # Поиск по ID или username
    if user_input.isdigit():
        target_user_id = int(user_input)
    else:
        username = user_input.replace("@", "").lower()
        users_data = load_users_data()
        for uid, data in users_data.items():
            saved_username = data.get("username")
            if saved_username and saved_username.lower() == username:
                target_user_id = int(uid)
                break
    
    if not target_user_id:
        await message.answer(
            f"❌ Пользователь `{user_input}` не найден.\n"
            f"Пользователь должен хотя бы раз запустить бота командой /start",
            parse_mode="Markdown"
        )
        await state.clear()
        return
    
    # Выдаём подписку на 30 дней
    expiry_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    update_user_data(target_user_id, {"subscription_until": expiry_date})
    
    user_data = get_user_data(target_user_id)
    display_name = user_data.get("username") or str(target_user_id)
    
    await message.answer(
        f"✅ *Подписка выдана!*\n\n"
        f"Пользователь: `{display_name}`\n"
        f"ID: `{target_user_id}`\n"
        f"Активна до: `{expiry_date}`",
        parse_mode="Markdown"
    )
    
    # Уведомляем пользователя
    try:
        await bot.send_message(
            target_user_id,
            f"🎉 *Поздравляем!*\n\n"
            f"Вам выдана премиум подписка до `{expiry_date}`\n\n"
            f"Теперь у вас неограниченное количество запросов!\n"
            f"📸 Отправляйте фото - я решу любые задачи!",
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
    total_requests_all = 0
    
    today = datetime.now().strftime("%Y-%m-%d")
    
    for uid, data in users_data.items():
        # Подсчёт активных подписок
        sub_until = data.get("subscription_until")
        if sub_until:
            try:
                expiry = datetime.strptime(sub_until, "%Y-%m-%d")
                if expiry > datetime.now():
                    active_subs += 1
            except:
                pass
        
        if data.get("last_reset") == today:
            total_requests_today += data.get("requests_today", 0)
        total_requests_all += data.get("total_requests", 0)
    
    stats_text = f"""📊 *Статистика бота*

👥 *Всего пользователей:* {total_users}
💎 *Активных подписок:* {active_subs}
📝 *Запросов сегодня:* {total_requests_today}
📈 *Всего запросов:* {total_requests_all}
🧠 *Активных диалогов:* {len(chat_histories)}

📅 *Данные на:* {datetime.now().strftime('%d.%m.%Y %H:%M')}

🎁 *Лимит бесплатных:* 20/день
💎 *Цена подписки:* 30 звёзд/месяц"""
    
    await callback.message.edit_text(stats_text, parse_mode="Markdown")
    await callback.answer()

@dp.message(Command("cancel"))
async def cancel_admin(message: Message, state: FSMContext):
    """Отмена админ-действия"""
    await state.clear()
    await message.answer("❌ Действие отменено", reply_markup=get_main_keyboard(message.from_user.id))

# ========== ОСНОВНЫЕ ОБРАБОТЧИКИ СООБЩЕНИЙ ==========

@dp.message(ChatState.waiting_for_question, lambda message: message.photo)
async def handle_photo(message: Message):
    user_id = message.from_user.id
    
    can_request, error_msg = can_make_request(user_id)
    if not can_request:
        await message.answer(error_msg, parse_mode="Markdown", reply_markup=get_main_keyboard(user_id))
        return
    
    photo = message.photo[-1]
    user_question = message.caption or "Что на этом изображении?"
    
    await bot.send_chat_action(message.chat.id, "typing")
    thinking_msg = await message.answer("🔍 *Анализирую изображение...*", parse_mode="Markdown")
    
    try:
        extracted_text = await extract_text_from_photo(photo.file_id)
        
        if not has_active_subscription(user_id):
            increment_request(user_id)
        
        answer, used_model = await ask_groq(user_id, user_question, extracted_text)
        
        add_to_history(user_id, "user", f"[Фото] {user_question}")
        add_to_history(user_id, "assistant", answer[:500])
        
        await thinking_msg.delete()
        
        if extracted_text and extracted_text != "Текст на фото не обнаружен" and len(extracted_text) < 500:
            await message.answer(f"📝 *Распознано:*\n```\n{extracted_text[:300]}\n```", parse_mode="Markdown")
        
        answer_parts = smart_split_text(answer)
        model_name = MODELS.get(used_model, "")
        
        for i, part in enumerate(answer_parts):
            footer = f"\n\n— {model_name}" if i == len(answer_parts)-1 and model_name else ""
            await message.answer(part + footer, parse_mode="Markdown")
        
        if not has_active_subscription(user_id):
            remaining = get_remaining_free_requests(user_id)
            if remaining <= 5:
                await message.answer(f"⚠️ *Осталось {remaining} бесплатных запросов на сегодня*\n\n💎 Купи подписку за 30 звёзд для безлимита!", parse_mode="Markdown")
                
    except Exception as e:
        await thinking_msg.delete()
        await message.answer(f"❌ Ошибка: {str(e)[:200]}", reply_markup=get_main_keyboard(user_id))

@dp.message(ChatState.waiting_for_question)
async def handle_text(message: Message):
    question = message.text.strip()
    
    # Игнорируем кнопки меню
    menu_buttons = ["📊 Статус", "💎 Купить подписку", "🧠 Выбрать модель", 
                    "🔄 Сбросить диалог", "❓ Помощь", "ℹ️ О боте"]
    if any(question == btn or question.startswith("📊 Статус") for btn in menu_buttons):
        return
    
    if not question:
        return
    
    user_id = message.from_user.id
    
    if len(question) > 3000:
        await message.answer("⚠️ *Слишком длинный запрос* (макс 3000 символов)", parse_mode="Markdown")
        return
    
    can_request, error_msg = can_make_request(user_id)
    if not can_request:
        await message.answer(error_msg, parse_mode="Markdown", reply_markup=get_main_keyboard(user_id))
        return
    
    if not has_active_subscription(user_id):
        increment_request(user_id)
    
    await bot.send_chat_action(message.chat.id, "typing")
    thinking_msg = await message.answer("🤔 *Думаю...*", parse_mode="Markdown")
    
    try:
        answer, used_model = await ask_groq(user_id, question)
        
        add_to_history(user_id, "user", question[:500])
        add_to_history(user_id, "assistant", answer[:500])
        
        await thinking_msg.delete()
        
        answer_parts = smart_split_text(answer)
        model_name = MODELS.get(used_model, "")
        
        for i, part in enumerate(answer_parts):
            footer = f"\n\n— {model_name}" if i == len(answer_parts)-1 and model_name else ""
            await message.answer(part + footer, parse_mode="Markdown")
        
        if not has_active_subscription(user_id):
            remaining = get_remaining_free_requests(user_id)
            if remaining <= 5:
                await message.answer(f"⚠️ *Осталось {remaining} запросов на сегодня*\n\n💎 Купи подписку за 30 звёзд!", parse_mode="Markdown")
            
    except Exception as e:
        await thinking_msg.delete()
        await message.answer(f"❌ Ошибка: {str(e)[:200]}", reply_markup=get_main_keyboard(user_id))

# ========== ЗАПУСК ==========

async def main():
    print("=" * 60)
    print("🤖 ГИБРИДНЫЙ AI-АССИСТЕНТ С ПОДПИСКАМИ")
    print("=" * 60)
    print(f"👑 Владелец: {OWNER_ID}")
    print(f"💰 Подписка: {STAR_PRICE} звёзд/месяц")
    print(f"🎁 Бесплатно: 20 запросов/день")
    print("=" * 60)
    
    for file in [DATA_FILE, HISTORY_FILE]:
        if not os.path.exists(file):
            with open(file, 'w', encoding='utf-8') as f:
                json.dump({}, f)
            print(f"📁 Создан {file}")
    
    history_data = load_chat_history()
    for user_id, history in history_data.items():
        chat_histories[user_id] = history
    print(f"📁 Загружена история для {len(chat_histories)} пользователей")
    
    # Проверка Tesseract
    try:
        result = subprocess.run(['tesseract', '--version'], capture_output=True, text=True)
        if result.returncode == 0:
            print("✅ Tesseract OCR установлен")
    except:
        print("⚠️ Tesseract не найден. Установите: sudo apt-get install tesseract-ocr tesseract-ocr-rus")
    
    print("=" * 60)
    print("✅ БОТ ГОТОВ К РАБОТЕ!")
    print("=" * 60)
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())