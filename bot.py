import asyncio
import aiohttp
import json
import os
import re
import base64
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.client.bot import DefaultBotProperties
from collections import defaultdict
from typing import Tuple, Optional
import tempfile
import subprocess

# ========== КОНФИГУРАЦИЯ ==========
GROQ_API_KEY = "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"
OPENROUTER_API_KEY = "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"
OWNER_ID = 5439940299
STAR_PRICE = 30

DATA_FILE = "users_data.json"
HISTORY_FILE = "chat_history.json"
MAX_HISTORY_LENGTH = 15

# ========== ВСЕ БЕСПЛАТНЫЕ МОДЕЛИ ==========
MODELS = {
    # Groq (текст, очень быстро)
    "llama-3.3-70b-versatile": "🦙 Llama 70B (Groq, мощная)",
    "llama-3.1-8b-instant": "⚡ Llama 8B (Groq, быстрая)",
    # Groq Vision (анализ изображений!) — НОВИНКА
    "llama-4-scout-17b-16e-instruct": "👁️ Llama 4 Scout (Groq, Vision)",
    # OpenRouter (бесплатные модели)
    "google/gemma-4-31b-it:free": "🌟 Gemma 4 31B (OpenRouter)",
    "nvidia/nemotron-nano-12b-v2-vl:free": "🔷 Nemotron 12B VL (OpenRouter, Vision)",
    "qwen/qwen3.6-plus-preview:free": "🐉 Qwen 3.6 Plus (1M контекст)",
    "meta-llama/llama-3.3-70b-instruct:free": "🦙 Llama 70B (OpenRouter)",
}

DEFAULT_MODEL = "llama-3.3-70b-versatile"
FAST_MODEL = "llama-3.1-8b-instant"
DEFAULT_VISION_MODEL = "llama-4-scout-17b-16e-instruct"

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

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
    user_data = get_user_data(user_id)
    return user_data.get("subscription_until")

def give_subscription(user_id: int, days: int = 30):
    expiry_date = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
    update_user_data(user_id, {"subscription_until": expiry_date})

def remove_subscription(user_id: int):
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
            "subscription_until": None
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
    
    if has_active_subscription(user_id):
        return True, None
    
    if user_data["requests_today"] >= 20:
        return False, "⏰ *Лимит 20 бесплатных запросов в день исчерпан!*\n\n💎 Оформи подписку за 30 звёзд в месяц для безлимита.\n\n👤 Напиши @SedoyDiada"
    
    return True, None

def increment_request(user_id: int):
    if has_active_subscription(user_id):
        return
    user_data = get_user_data(user_id)
    reset_daily_requests(user_id)
    new_count = user_data["requests_today"] + 1
    total = user_data.get("total_requests", 0) + 1
    update_user_data(user_id, {"requests_today": new_count, "total_requests": total})

def get_remaining_free_requests(user_id: int):
    if has_active_subscription(user_id):
        return "∞"
    user_data = get_user_data(user_id)
    reset_daily_requests(user_id)
    return max(0, 20 - user_data["requests_today"])

def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID

# ========== OPENROUTER API (БЕСПЛАТНЫЕ МОДЕЛИ) ==========
async def ask_openrouter(question: str, model: str, system_prompt: str = None, image_base64: str = None) -> str:
    """Универсальный запрос к OpenRouter"""
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://t.me/math_bot",
        "X-Title": "Math Assistant Bot"
    }
    
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    
    if image_base64:
        messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": question},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}
            ]
        })
    else:
        messages.append({"role": "user", "content": question})
    
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": 1500,
        "temperature": 0.2
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(OPENROUTER_URL, headers=headers, json=payload, timeout=60) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data["choices"][0]["message"]["content"]
                elif resp.status == 429:
                    return "⏰ Лимит запросов. Попробуй через минуту."
                else:
                    return f"❌ OpenRouter ошибка: {resp.status}"
        except asyncio.TimeoutError:
            return "⏰ Время ожидания истекло"
        except Exception as e:
            return f"⚠️ Ошибка: {str(e)}"

# ========== АНАЛИЗ ИЗОБРАЖЕНИЙ (LLAMA 4 SCOUT) ==========
async def analyze_image_with_vision(image_base64: str, user_question: str) -> str:
    """Анализирует изображение через Llama 4 Scout (Groq) — бесплатно и быстро!"""
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": DEFAULT_VISION_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": f"Ты — AI-репетитор по математике. Реши задачу с этого изображения. Если видишь уравнение — реши его пошагово. Ответь на русском языке.\n\nВопрос: {user_question}"
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}
                    }
                ]
            }
        ],
        "max_tokens": 1500,
        "temperature": 0.2
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(GROQ_API_URL, headers=headers, json=payload, timeout=60) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data["choices"][0]["message"]["content"]
                else:
                    return await fallback_vision(image_base64, user_question)
        except Exception as e:
            return await fallback_vision(image_base64, user_question)

async def fallback_vision(image_base64: str, user_question: str) -> str:
    """Резервный вариант через OpenRouter (если Llama 4 Scout недоступна)"""
    return await ask_openrouter(
        user_question,
        "nvidia/nemotron-nano-12b-v2-vl:free",
        "Ты — AI-репетитор по математике. Реши задачу с этого изображения. Ответь на русском.",
        image_base64
    )

# ========== ЗАПРОС К GROQ (ТЕКСТ) ==========
async def ask_groq(user_id: int, question: str, use_fast: bool = False) -> Tuple[str, str]:
    """Быстрый текстовый запрос к Groq"""
    task_type = detect_task_type(question)
    
    if use_fast or (task_type['use_fast_model'] and len(question) < 200):
        model = user_models.get(user_id, FAST_MODEL)
    else:
        model = user_models.get(user_id, DEFAULT_MODEL)
    
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    
    context = get_context_messages(user_id, max_messages=6)
    
    messages = [{"role": "system", "content": HYBRID_SYSTEM_PROMPT}]
    for msg in context[-4:]:
        messages.append(msg)
    messages.append({"role": "user", "content": question})
    
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.6 if not task_type['is_math'] else 0.2,
        "max_tokens": 1200
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(GROQ_API_URL, headers=headers, json=payload, timeout=45) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    answer = data["choices"][0]["message"]["content"]
                    if len(answer) > 3500:
                        answer = answer[:3500] + "\n\n[Ответ сокращён...]"
                    return answer, model
                else:
                    return await fallback_openrouter(question), model
        except Exception as e:
            return f"⚠️ Ошибка: {str(e)}", model

async def fallback_openrouter(question: str) -> str:
    """Резерв через OpenRouter"""
    return await ask_openrouter(
        question,
        "qwen/qwen3.6-plus-preview:free",
        HYBRID_SYSTEM_PROMPT
    )

def detect_task_type(text: str) -> dict:
    text_lower = text.lower()
    math_patterns = [r'[0-9\+\-\*\/\^=√∫∑∂]', r'уравнени[ея]', r'реши', r'найди', r'производн']
    is_math = any(re.search(p, text_lower) for p in math_patterns)
    return {'is_math': is_math, 'use_fast_model': not is_math and len(text) < 100}

def smart_split_text(text: str, max_length: int = 3500) -> list:
    if len(text) <= max_length:
        return [text]
    parts, current = [], ""
    for para in text.split('\n\n'):
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
    
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=f"📊 Статус | {status_text}")],
            [KeyboardButton(text="💎 Купить подписку"), KeyboardButton(text="🧠 Выбрать модель")],
            [KeyboardButton(text="🔄 Сбросить диалог"), KeyboardButton(text="❓ Помощь")]
        ],
        resize_keyboard=True
    )

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
✅ Анализ фото через Llama 4 Scout
✅ Память диалога

Просто напиши вопрос или отправь фото!"""
    else:
        welcome_msg = f"""🌟 *Добро пожаловать в гибридный AI-ассистент!*

🎁 *Бесплатно:* {remaining}/20 запросов в день

👁️ *НОВИНКА:* Llama 4 Scout с анализом изображений!
📸 Отправь фото с уравнением — я решу!

💎 *Премиум за 30 звёзд:* безлимитные запросы

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

👁️ *Доступные модели:*
• Llama 4 Scout (анализ фото!)
• Qwen 3.6 Plus (1M контекст)
• Gemma 4, Nemotron VL

💎 *Купи подписку за 30 звёзд для безлимита!*"""
    
    await message.answer(status_text, parse_mode="Markdown", reply_markup=get_main_keyboard(user_id))

@dp.message(lambda message: message.text == "💎 Купить подписку")
async def buy_subscription_button(message: Message):
    await message.answer(
        f"💎 *Премиум подписка*\n\n"
        f"💰 *Цена:* {STAR_PRICE} звёзд\n"
        f"📅 *Срок:* 1 месяц\n"
        f"✅ *Преимущества:*\n"
        f"• Безлимитные запросы\n"
        f"• Анализ фото через Llama 4 Scout\n"
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
        "👁️ **Llama 4 Scout** — анализ изображений (НОВИНКА!)\n"
        "🦙 **Llama 70B** — мощная, для сложных задач\n"
        "⚡ **Llama 8B** — быстрая, для простых вопросов\n"
        "🌟 **Gemma 4** — от Google\n"
        "🔷 **Nemotron VL** — Vision модель\n"
        "🐉 **Qwen 3.6 Plus** — 1M контекст",
        reply_markup=model_choice_keyboard(),
        parse_mode="Markdown"
    )

@dp.message(lambda message: message.text == "❓ Помощь")
async def help_button(message: Message):
    help_text = """❓ *Как пользоваться ботом*

📸 *Фото с задачами (НОВИНКА!):*
• Отправь фото с уравнением
• Llama 4 Scout проанализирует и решит
• Распознаёт дроби, корни, степени

📝 *Текст:* просто напиши вопрос
• x² - 5x + 6 = 0
• Найди производную x³+2x²

🎁 *Тарифы:*
• Бесплатно: 20 запросов/день
• Премиум: 30⭐/месяц — безлимит

👁️ *Доступные Vision-модели:*
• Llama 4 Scout (Groq)
• Nemotron VL (OpenRouter)
• Gemma 4 (OpenRouter)"""
    
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

# ========== АДМИН-КОМАНДЫ ==========
@dp.message(Command("admin"))
async def admin_panel(message: Message):
    if not is_owner(message.from_user.id):
        await message.answer("⛔ Доступ запрещён.")
        return
    
    await message.answer(
        "👑 *Админ панель*\n\nВыбери действие:",
        reply_markup=admin_keyboard(),
        parse_mode="Markdown"
    )

@dp.callback_query(lambda c: c.data == "admin_give_sub")
async def admin_give_sub_prompt(callback: CallbackQuery, state: FSMContext):
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
    if not is_owner(message.from_user.id):
        await message.answer("⛔ Доступ запрещён")
        await state.clear()
        return
    
    user_input = message.text.strip()
    target_user_id = None
    
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
        await message.answer(f"❌ Пользователь `{user_input}` не найден.", parse_mode="Markdown")
        await state.clear()
        return
    
    expiry_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    update_user_data(target_user_id, {"subscription_until": expiry_date})
    
    user_data = get_user_data(target_user_id)
    display_name = user_data.get("username") or str(target_user_id)
    
    await message.answer(
        f"✅ *Подписка выдана!*\n\n"
        f"Пользователь: `{display_name}`\n"
        f"Активна до: `{expiry_date}`",
        parse_mode="Markdown"
    )
    
    try:
        await bot.send_message(
            target_user_id,
            f"🎉 *Вам выдана премиум подписка до {expiry_date}!*\n\n"
            f"📸 Отправляйте фото — Llama 4 Scout решит любые задачи!",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard(target_user_id)
        )
    except Exception as e:
        await message.answer(f"⚠️ Не удалось уведомить пользователя: {e}")
    
    await state.clear()

@dp.callback_query(lambda c: c.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
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

👁️ *Llama 4 Scout:* Активен (анализ фото)
🎁 *Лимит:* 20 бесплатных/день
💎 *Подписка:* 30 звёзд/месяц"""
    
    await callback.message.edit_text(stats_text, parse_mode="Markdown")
    await callback.answer()

@dp.message(Command("cancel"))
async def cancel_admin(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Отменено", reply_markup=get_main_keyboard(message.from_user.id))

# ========== ОСНОВНЫЕ ОБРАБОТЧИКИ ==========
@dp.message(ChatState.waiting_for_question, lambda message: message.photo)
async def handle_photo(message: Message):
    user_id = message.from_user.id
    
    can_request, error_msg = can_make_request(user_id)
    if not can_request:
        await message.answer(error_msg, parse_mode="Markdown", reply_markup=get_main_keyboard(user_id))
        return
    
    photo = message.photo[-1]
    user_question = message.caption or "Реши уравнение на этом фото"
    
    await bot.send_chat_action(message.chat.id, "typing")
    thinking_msg = await message.answer("👁️ **Анализирую изображение через Llama 4 Scout...**", parse_mode="Markdown")
    
    try:
        file = await bot.get_file(photo.file_id)
        file_bytes = await bot.download_file(file.file_path)
        image_base64 = base64.b64encode(file_bytes.getvalue()).decode('utf-8')
        
        answer = await analyze_image_with_vision(image_base64, user_question)
        
        if not has_active_subscription(user_id):
            increment_request(user_id)
        
        add_to_history(user_id, "user", f"[Фото] {user_question}")
        add_to_history(user_id, "assistant", answer[:500])
        
        await thinking_msg.delete()
        
        answer_parts = smart_split_text(answer)
        for i, part in enumerate(answer_parts):
            footer = "\n\n— 👁️ Llama 4 Scout" if i == len(answer_parts)-1 else ""
            await message.answer(part + footer, parse_mode="Markdown")
        
        if not has_active_subscription(user_id):
            remaining = get_remaining_free_requests(user_id)
            if isinstance(remaining, int) and remaining <= 5:
                await message.answer(f"⚠️ *Осталось {remaining} запросов на сегодня*\n\n💎 Купи подписку за 30 звёзд!", parse_mode="Markdown")
                
    except Exception as e:
        await thinking_msg.delete()
        await message.answer(f"❌ Ошибка: {str(e)[:200]}", reply_markup=get_main_keyboard(user_id))

@dp.message(ChatState.waiting_for_question)
async def handle_text(message: Message):
    question = message.text.strip()
    
    menu_buttons = ["📊 Статус", "💎 Купить подписку", "🧠 Выбрать модель", 
                    "🔄 Сбросить диалог", "❓ Помощь", "ℹ️ О боте"]
    if any(question == btn for btn in menu_buttons):
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
            if isinstance(remaining, int) and remaining <= 5:
                await message.answer(f"⚠️ *Осталось {remaining} запросов на сегодня*\n\n💎 Купи подписку за 30 звёзд!", parse_mode="Markdown")
            
    except Exception as e:
        await thinking_msg.delete()
        await message.answer(f"❌ Ошибка: {str(e)[:200]}", reply_markup=get_main_keyboard(user_id))

# ========== ЗАПУСК ==========
async def main():
    print("=" * 60)
    print("🤖 ГИБРИДНЫЙ AI-АССИСТЕНТ С Llama 4 Scout")
    print("=" * 60)
    print(f"👑 Владелец: {OWNER_ID}")
    print(f"💰 Подписка: {STAR_PRICE} звёзд/месяц")
    print(f"🎁 Бесплатно: 20 запросов/день")
    print(f"👁️ Vision модель: Llama 4 Scout (Groq)")
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
    
    print("=" * 60)
    print("✅ БОТ ГОТОВ К РАБОТЕ!")
    print("📌 Что умеет:")
    print("   • 👁️ Анализировать фото через Llama 4 Scout")
    print("   • 🧮 Решать уравнения и примеры")
    print("   • 💻 Помогать с программированием")
    print("   • 📝 Переводить и анализировать текст")
    print("=" * 60)
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())