import asyncio
import aiohttp
import json
import os
import re
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
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

# OpenRouter API (Molmo2 8B — бесплатно!)
OPENROUTER_API_KEY = "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"  # Получите на https://openrouter.ai/keys
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

DATA_FILE = "users_data.json"
HISTORY_FILE = "chat_history.json"
MAX_HISTORY_LENGTH = 15

# Модели
MODELS = {
    "llama-3.3-70b-versatile": "🦙 Llama 70B (Groq, текст)",
    "llama-3.1-8b-instant": "⚡ Llama 8B (Groq, быстрая)",
    "molmo-2-8b:free": "👁️ Molmo2 8B (анализ фото, бесплатно)"
}

DEFAULT_MODEL = "llama-3.3-70b-versatile"
FAST_MODEL = "llama-3.1-8b-instant"
VISION_MODEL = "molmo-2-8b:free"

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

bot = Bot(
    token="8857441987:AAH18rhUKO8MvxzJvm0TPlCaxksHrlHycww",
    default=DefaultBotProperties(parse_mode="Markdown")
)

dp = Dispatcher(storage=MemoryStorage())
user_models = {}
chat_histories = defaultdict(list)

# ========== СИСТЕМНЫЙ ПРОМПТ ==========

HYBRID_SYSTEM_PROMPT = """Ты — универсальный AI-ассистент с расширенными возможностями.

ТВОИ ВОЗМОЖНОСТИ:

1. 📚 **ОБЩИЕ ЗНАНИЯ** - отвечай на любые вопросы из любой области
2. 🧮 **МАТЕМАТИКА** - решай уравнения, примеры, производные, интегралы, задачи
3. 💻 **ПРОГРАММИРОВАНИЕ** - пиши код, объясняй алгоритмы, отлаживай
4. 📝 **ПЕРЕВОД** - переводи с/на любые языки
5. 📖 **ТЕКСТОВЫЙ АНАЛИЗ** - анализируй, реферируй, пересказывай
6. ✍️ **КРЕАТИВ** - пиши стихи, рассказы, сценарии

ПРАВИЛА ОТВЕТОВ:
- ВСЕГДА отвечай на русском, если вопрос не на другом языке
- Если задача сложная - давай пошаговое решение
- Формулы оформляй в LaTeX: $$...$$ для отдельных, $...$ для встроенных
- Код оформляй в блоки ```language
- Будь дружелюбным и полезным"""

# ========== MOLMO2 8B VISION API (ЧЕРЕЗ OPENROUTER) ==========

async def ask_molmo_vision(image_base64: str, user_question: str) -> str:
    """
    Отправляет изображение в Molmo2 8B через OpenRouter (бесплатно!)
    """
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    
    # Добавляем реферальную информацию (необязательно, но полезно для OpenRouter)
    headers["HTTP-Referer"] = "https://t.me/your_bot"
    headers["X-Title"] = "Math Assistant Bot"
    
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": f"""Ты — AI-репетитор по математике. Реши задачу с этого изображения.

Правила:
1. Если видишь уравнение — реши его пошагово
2. Распознавай дроби, корни, степени
3. Ответь на русском языке
4. В конце напиши ОТВЕТ:

Вопрос пользователя: {user_question}"""
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{image_base64}"
                    }
                }
            ]
        }
    ]
    
    payload = {
        "model": VISION_MODEL,  # molmo-2-8b:free — полностью бесплатно!
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": 1500
    }
    
    timeout = aiohttp.ClientTimeout(total=60)
    
    async with aiohttp.ClientSession(timeout=timeout) as session:
        try:
            async with session.post(OPENROUTER_API_URL, headers=headers, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    answer = data["choices"][0]["message"]["content"]
                    return answer
                elif resp.status == 429:
                    return "⏰ Слишком много запросов. Попробуй через минуту."
                else:
                    error_text = await resp.text()
                    print(f"❌ OpenRouter ошибка: {resp.status} - {error_text[:200]}")
                    return f"❌ Ошибка API: {resp.status}"
        except asyncio.TimeoutError:
            return "⏰ Время ожидания истекло"
        except Exception as e:
            return f"⚠️ Ошибка: {str(e)}"

# ========== GROQ API (ТЕКСТ) ==========

async def ask_groq(user_id: int, question: str) -> Tuple[str, str]:
    """Обычный запрос к Groq для текста"""
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    
    task_type = detect_task_type(question)
    
    if task_type['use_fast_model'] and len(question) < 200:
        model = user_models.get(user_id, FAST_MODEL)
    else:
        model = user_models.get(user_id, DEFAULT_MODEL)
    
    context = get_context_messages(user_id, max_messages=6)
    
    messages = [
        {"role": "system", "content": HYBRID_SYSTEM_PROMPT}
    ]
    
    for msg in context[-4:]:
        messages.append(msg)
    
    messages.append({"role": "user", "content": question})
    
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
            return "⏰ Время ожидания истекло", model
        except Exception as e:
            return f"⚠️ Ошибка: {str(e)}", model

# ========== ОСТАЛЬНЫЕ ФУНКЦИИ ==========

def detect_task_type(text: str) -> dict:
    text_lower = text.lower()
    math_patterns = [r'[0-9\+\-\*\/\^=√∫∑∂]', r'уравнени[ея]', r'реши', r'найди']
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
            "total_requests": 0
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
            "total_requests": 0
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
    if user_data["requests_today"] >= 50:
        return False, "⏰ *Лимит 50 запросов в день исчерпан!*\n\nВозвращайся завтра!"
    return True, None

def increment_request(user_id: int):
    user_data = get_user_data(user_id)
    reset_daily_requests(user_id)
    new_count = user_data["requests_today"] + 1
    total = user_data.get("total_requests", 0) + 1
    update_user_data(user_id, {"requests_today": new_count, "total_requests": total})

def get_remaining_free_requests(user_id: int) -> int:
    user_data = get_user_data(user_id)
    reset_daily_requests(user_id)
    return max(0, 50 - user_data["requests_today"])

def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID

# ========== КЛАВИАТУРЫ ==========

def get_main_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    remaining = get_remaining_free_requests(user_id)
    
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=f"📊 Статус | 🎫 {remaining}/50")],
            [KeyboardButton(text="🧠 Выбрать модель"), KeyboardButton(text="🔄 Сбросить диалог")],
            [KeyboardButton(text="❓ Помощь"), KeyboardButton(text="ℹ️ О боте")]
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
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="❌ Закрыть", callback_data="close")]
    ])

# ========== СОСТОЯНИЯ ==========

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
    
    welcome_msg = f"""🤖 *Гибридный AI-ассистент с Molmo2 8B*

Привет! Теперь я использую **Molmo2 8B** — мощную бесплатную модель для анализа изображений!

📸 *Что умеет:*
• Распознавать уравнения и формулы с фото
• Решать математические задачи пошагово
• Видеть дроби, корни, степени

🎁 *Бесплатно:* {remaining}/50 запросов в день

📤 *Просто отправь фото с уравнением!*"""

    await message.answer(welcome_msg, reply_markup=get_main_keyboard(user_id), parse_mode="Markdown")
    await state.set_state(ChatState.waiting_for_question)

@dp.message(lambda message: message.text and message.text.startswith("📊 Статус"))
async def status_button(message: Message):
    user_id = message.from_user.id
    remaining = get_remaining_free_requests(user_id)
    user_data = get_user_data(user_id)
    total = user_data.get("total_requests", 0)
    model = user_models.get(user_id, DEFAULT_MODEL)
    model_name = MODELS.get(model, "Неизвестно")[:40]
    
    status_text = f"""📊 *Ваша статистика*

🎫 *Тариф:* Бесплатный
📝 *Осталось сегодня:* {remaining}/50
📈 *Всего запросов:* {total}

🧠 *Текущая модель:* {model_name}

✨ *Возможности:*
• 📸 Анализ фото через Molmo2 8B
• 🧮 Решение уравнений и примеров
• 💻 Помощь с программированием"""

    await message.answer(status_text, parse_mode="Markdown", reply_markup=get_main_keyboard(user_id))

@dp.message(lambda message: message.text == "🧠 Выбрать модель")
async def change_model_button(message: Message):
    await message.answer(
        "🧠 *Выбери модель AI:*\n\n"
        "🦙 **Llama 70B** — мощная, для сложных текстовых задач\n"
        "⚡ **Llama 8B** — быстрая, для простых вопросов\n"
        "👁️ **Molmo2 8B** — анализ изображений и уравнений (рекомендуется для фото)",
        reply_markup=model_choice_keyboard(),
        parse_mode="Markdown"
    )

@dp.message(lambda message: message.text == "❓ Помощь")
async def help_button(message: Message):
    help_text = """❓ *Как пользоваться ботом*

📸 *Фото с задачами:*
• Отправь фото с уравнением
• Molmo2 8B проанализирует и решит
• Распознаёт дроби, корни, степени

📝 *Текст:*
• Просто напиши вопрос
• x² - 5x + 6 = 0
• Найди производную x³+2x²

🎁 *Бесплатно:* 50 запросов в день"""

    await message.answer(help_text, parse_mode="Markdown", reply_markup=get_main_keyboard(message.from_user.id))

@dp.message(lambda message: message.text == "ℹ️ О боте")
async def info_button(message: Message):
    info_text = """🤖 *Гибридный AI-ассистент*

Версия: 4.1 (с Molmo2 8B)

📌 *Технологии:*
• Groq API (текстовые запросы)
• OpenRouter + Molmo2 8B (анализ фото)
• Llama 70B / 8B

🎁 *Тариф:* Полностью бесплатный
• 50 запросов в день
• Molmo2 8B — безлимитный анализ фото

👨‍💻 *Разработчик:* @SedoyDiada"""

    await message.answer(info_text, parse_mode="Markdown", reply_markup=get_main_keyboard(message.from_user.id))

@dp.message(lambda message: message.text == "🔄 Сбросить диалог")
async def reset_button(message: Message, state: FSMContext):
    clear_history(message.from_user.id)
    await state.clear()
    await state.set_state(ChatState.waiting_for_question)
    await message.answer("🔄 *Диалог сброшен!*", parse_mode="Markdown", reply_markup=get_main_keyboard(message.from_user.id))

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

# ========== ГЛАВНАЯ ОБРАБОТКА ФОТО (ЧЕРЕЗ MOLMO2) ==========

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
    thinking_msg = await message.answer("👁️ *Анализирую изображение через Molmo2 8B...*", parse_mode="Markdown")
    
    try:
        # Конвертируем фото в base64
        file = await bot.get_file(photo.file_id)
        file_bytes = await bot.download_file(file.file_path)
        image_base64 = base64.b64encode(file_bytes.getvalue()).decode('utf-8')
        
        increment_request(user_id)
        
        # Отправляем в Molmo2 через OpenRouter
        answer = await ask_molmo_vision(image_base64, user_question)
        
        # Сохраняем в историю
        add_to_history(user_id, "user", f"[Фото через Molmo2] {user_question}")
        add_to_history(user_id, "assistant", answer[:500])
        
        await thinking_msg.delete()
        
        # Отправляем ответ
        answer_parts = smart_split_text(answer)
        
        for i, part in enumerate(answer_parts):
            footer = "\n\n— 👁️ Molmo2 8B" if i == len(answer_parts)-1 else ""
            await message.answer(part + footer, parse_mode="Markdown", reply_markup=get_main_keyboard(user_id) if i == 0 else None)
        
        # Напоминание о лимите
        remaining = get_remaining_free_requests(user_id)
        if remaining <= 10:
            await message.answer(f"📊 *Осталось {remaining} запросов на сегодня*", parse_mode="Markdown")
                
    except Exception as e:
        await thinking_msg.delete()
        await message.answer(f"❌ Ошибка при анализе фото: {str(e)[:200]}\n\nПопробуй написать задачу текстом.", reply_markup=get_main_keyboard(user_id))

# ========== ОБРАБОТКА ТЕКСТОВЫХ ЗАПРОСОВ (ЧЕРЕЗ GROQ) ==========

@dp.message(ChatState.waiting_for_question)
async def handle_text(message: Message):
    question = message.text.strip()
    
    # Игнорируем кнопки
    buttons = ["📊 Статус", "🧠 Выбрать модель", "🔄 Сбросить диалог", "❓ Помощь", "ℹ️ О боте"]
    if any(question == btn or question.startswith("📊 Статус") for btn in buttons):
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
            await message.answer(part + footer, parse_mode="Markdown", reply_markup=get_main_keyboard(user_id) if i == 0 else None)
        
        remaining = get_remaining_free_requests(user_id)
        if remaining <= 10:
            await message.answer(f"📊 *Осталось {remaining} запросов на сегодня*", parse_mode="Markdown")
            
    except Exception as e:
        await thinking_msg.delete()
        await message.answer(f"❌ Ошибка: {str(e)[:200]}", reply_markup=get_main_keyboard(user_id))

# ========== АДМИН-ПАНЕЛЬ ==========

@dp.message(Command("admin"))
async def admin_panel(message: Message):
    if not is_owner(message.from_user.id):
        await message.answer("⛔ Доступ запрещён")
        return
    await message.answer("👑 *Админ панель*", reply_markup=admin_keyboard(), parse_mode="Markdown")

@dp.callback_query(lambda c: c.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if not is_owner(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён")
        return
    
    users_data = load_users_data()
    total_users = len(users_data)
    total_requests_today = 0
    total_requests_all = 0
    
    today = datetime.now().strftime("%Y-%m-%d")
    
    for user_id, data in users_data.items():
        if data.get("last_reset") == today:
            total_requests_today += data.get("requests_today", 0)
        total_requests_all += data.get("total_requests", 0)
    
    stats_text = f"""📊 *Статистика бота*

👥 *Пользователей:* {total_users}
📝 *Запросов сегодня:* {total_requests_today}
📈 *Всего запросов:* {total_requests_all}
🧠 *Активных диалогов:* {len(chat_histories)}

🎁 *Лимит:* 50 запросов/день
👁️ *Molmo2 8B:* Активен (бесплатно)

📅 *Дата:* {datetime.now().strftime('%d.%m.%Y %H:%M')}"""
    
    await callback.message.edit_text(stats_text, parse_mode="Markdown")
    await callback.answer()

@dp.message(Command("cancel"))
async def cancel_handler(message: Message, state: FSMContext):
    await state.set_state(ChatState.waiting_for_question)
    await message.answer("❌ Отменено", reply_markup=get_main_keyboard(message.from_user.id))

# ========== ЗАПУСК ==========

async def main():
    print("=" * 60)
    print("🤖 ГИБРИДНЫЙ AI-АССИСТЕНТ С MOLMO2 8B")
    print("=" * 60)
    print(f"👑 Владелец: {OWNER_ID}")
    print(f"🤖 Модели: Llama 70B, Llama 8B, Molmo2 8B (бесплатно!)")
    print(f"👁️ Molmo2: {'✅ Ключ установлен' if OPENROUTER_API_KEY != 'ваш_ключ_от_openrouter' else '❌ Нужен ключ'}")
    print(f"🎁 Лимит: 50 запросов/день")
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
    
    if OPENROUTER_API_KEY == "ваш_ключ_от_openrouter":
        print("⚠️ ВНИМАНИЕ! Не вставлен API ключ OpenRouter!")
        print("   Получите ключ бесплатно на https://openrouter.ai/keys")
    
    print("=" * 60)
    print("✅ БОТ ГОТОВ К РАБОТЕ!")
    print("📌 Что умеет:")
    print("   • 👁️ Анализировать фото через Molmo2 8B (бесплатно!)")
    print("   • 🧮 Решать уравнения и примеры")
    print("   • 📝 Текстовые запросы через Groq")
    print("=" * 60)
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())