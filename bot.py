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
OWNER_ID = 5439940299
STAR_PRICE = 30

DATA_FILE = "users_data.json"
HISTORY_FILE = "chat_history.json"
MAX_HISTORY_LENGTH = 25

# ========== ТОЛЬКО ДВЕ МОДЕЛИ ==========
MODELS = {
    "llama-3.3-70b-versatile": "🦙 Llama 70B (мощная, фото через OCR)",
    "llama-3.1-8b-instant": "⚡ Llama 8B (быстрая, фото через OCR)",
    
# НОВЫЕ БЕСПЛАТНЫЕ МОДЕЛИ (100% проверено!)
    "meta-llama/llama-4-scout-17b-16e-instruct": "👁️ Llama 4 Scout (анализ фото!)",
    "qwen/qwen3-32b": "🚀 Qwen 3 32B (высокий лимит 60 RPM)",
    "openai/gpt-oss-120b": "🏛️ GPT-OSS 120B (мощная)",
    "groq/compound": "💻 Compound (кодинг)", 
}

DEFAULT_MODEL = "llama-3.3-70b-versatile"
FAST_MODEL = "llama-3.1-8b-instant"

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

bot = Bot(
    token="8857441987:AAFxXSTX1fOiksCuymGDNerV3NNdEeV9Wx4",
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

ПРАВИЛА:
- Отвечай на русском
- Формулы в LaTeX: $$...$$
- Код в блоках ```language
- Будь полезным и дружелюбным"""

# ========== OCR ДЛЯ РАСПОЗНАВАНИЯ ТЕКСТА С ФОТО ==========
async def extract_text_from_photo(photo_file_id: str) -> str:
    """Извлекает текст с фото через Tesseract OCR (бесплатно, локально)"""
    try:
        file = await bot.get_file(photo_file_id)
        file_bytes = await bot.download_file(file.file_path)
        
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp_file:
            tmp_file.write(file_bytes.getvalue())
            tmp_path = tmp_file.name
        
        # Пробуем разные режимы для лучшего распознавания
        result = subprocess.run(
            ['tesseract', tmp_path, 'stdout', '-l', 'rus+eng', '--psm', '6'],
            capture_output=True, text=True, timeout=30
        )
        
        os.unlink(tmp_path)
        
        if result.returncode == 0 and result.stdout.strip():
            text = result.stdout.strip()
            # Нормализация дробей и формул
            text = re.sub(r'(\d+)\s*/\s*(\d+)', r'\1/\2', text)
            text = re.sub(r'(\d+)\s*=\s*(\d+)', r'\1=\2', text)
            text = re.sub(r'(\d+)\s*\+\s*(\d+)', r'\1+\2', text)
            text = re.sub(r'(\d+)\s*\*\s*(\d+)', r'\1*\2', text)
            return text
        return ""
        
    except Exception as e:
        print(f"❌ OCR ошибка: {e}")
        return ""

# ========== ОБРАБОТКА ФОТО (OCR + ЛЮБАЯ МОДЕЛЬ) ==========
async def process_photo_with_model(photo_file_id: str, user_question: str, model: str) -> Tuple[str, str]:
    """Распознаёт текст с фото через OCR, затем отправляет в модель"""
    
    # Шаг 1: распознаём текст с фото
    extracted_text = await extract_text_from_photo(photo_file_id)
    
    if not extracted_text:
        return None, model
    
    # Шаг 2: формируем запрос для модели
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    
    prompt = f"""📸 ПОЛЬЗОВАТЕЛЬ ОТПРАВИЛ ФОТО

Вот текст, который удалось распознать с фото:
{extracted_text}

Вопрос пользователя: {user_question}

Реши задачу. Если это уравнение — реши пошагово. Если текст не похож на математику — ответь по существу.
Ответь на русском языке."""
    
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": HYBRID_SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 1500,
        "temperature": 0.2
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(GROQ_API_URL, headers=headers, json=payload, timeout=60) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    answer = data["choices"][0]["message"]["content"]
                    # Показываем распознанный текст
                    preview = extracted_text[:400] + "..." if len(extracted_text) > 400 else extracted_text
                    full_answer = f"📝 *Распознано с фото:*\n```\n{preview}\n```\n\n{answer}"
                    return full_answer, model
                else:
                    return None, model
        except Exception as e:
            print(f"❌ Ошибка: {e}")
            return None, model

# ========== ОБЫЧНЫЙ ТЕКСТОВЫЙ ЗАПРОС ==========
async def ask_groq_text(user_id: int, question: str, model: str) -> Tuple[str, str]:
    """Обычный текстовый запрос к Groq"""
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
        "temperature": 0.6,
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
                    return f"❌ Ошибка API: {resp.status}", model
        except Exception as e:
            return f"⚠️ Ошибка: {str(e)}", model

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
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

def is_math_question(text: str) -> bool:
    """Определяет, похож ли вопрос на математический"""
    math_patterns = [r'\d+', r'[+\-*/=]', r'[xyz]', r'уравнени', r'реши', r'найди', r'вычисли']
    return any(re.search(p, text.lower()) for p in math_patterns)

# ========== РАБОТА С ПОДПИСКАМИ И ДАННЫМИ ==========
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

def load_users_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_users_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def clear_history(user_id: int):
    user_id_str = str(user_id)
    chat_histories[user_id_str] = []
    save_chat_history()

def save_chat_history():
    history_dict = dict(chat_histories)
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(history_dict, f, ensure_ascii=False, indent=2)

def load_chat_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
    return {}

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

def get_context_messages(user_id: int, max_messages: int = 6) -> list:
    history = get_user_history(user_id)
    return history[-max_messages:] if history else []

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
        welcome_msg = f"""🌟 *Добро пожаловать!*

💎 *Премиум подписка до {sub_until}*

✅ Безлимитные запросы
✅ Анализ фото через OCR
✅ Память диалога

Отправь фото с уравнением или напиши вопрос!"""
    else:
        welcome_msg = f"""🌟 *Добро пожаловать!*

🎁 *Бесплатно:* {remaining}/20 запросов в день

📸 *Отправь фото с уравнением* — я распознаю текст и решу!
🧠 *Память диалога* — помню контекст

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
    model_name = MODELS.get(model, "Неизвестно")
    
    if has_sub:
        sub_until = get_subscription_end_date(user_id)
        status_text = f"""📊 *Ваша статистика*

💎 *Премиум подписка*
📅 Активна до: {sub_until}
✅ Безлимитные запросы

🧠 *Модель:* {model_name}
📈 *Всего запросов:* {total}"""
    else:
        status_text = f"""📊 *Ваша статистика*

🎫 *Бесплатный тариф*
📝 *Осталось сегодня:* {remaining}/20
📈 *Всего запросов:* {total}

🧠 *Модель:* {model_name}

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
        f"• Анализ фото через OCR\n"
        f"• Память диалога\n\n"
        f"🔹 *Как купить:*\n"
        f"1. Отправь {STAR_PRICE} звёзд подарком\n"
        f"2. Напиши @SedoyDiada с чеком\n"
        f"3. Получи подписку\n\n"
        f"👤 *Владелец:* @SedoyDiada",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(message.from_user.id)
    )

@dp.message(lambda message: message.text == "🧠 Выбрать модель")
async def change_model_button(message: Message):
    await message.answer(
        "🧠 *Выбери модель:*\n\n"
        "🦙 **Llama 70B** — мощная, лучше для сложных уравнений\n"
        "⚡ **Llama 8B** — быстрая, для простых вопросов\n\n"
        "Обе модели умеют распознавать текст с фото через OCR!",
        reply_markup=model_choice_keyboard(),
        parse_mode="Markdown"
    )

@dp.message(lambda message: message.text == "❓ Помощь")
async def help_button(message: Message):
    help_text = """❓ *Как пользоваться ботом*

📸 *Фото с задачами:*
• Отправь фото с уравнением
• Я распознаю текст через OCR
• Решу задачу выбранной моделью

📝 *Текст:* просто напиши вопрос
• x² - 5x + 6 = 0
• Найди производную x³+2x²

🎁 *Тарифы:*
• Бесплатно: 20 запросов/день
• Премиум: 30⭐/месяц — безлимит

🧠 *Модели:*
• Llama 70B — мощная
• Llama 8B — быстрая"""
    
    await message.answer(help_text, parse_mode="Markdown", reply_markup=get_main_keyboard(message.from_user.id))

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

# ========== АДМИН-КОМАНДЫ ==========
@dp.message(Command("admin"))
async def admin_panel(message: Message):
    if not is_owner(message.from_user.id):
        await message.answer("⛔ Доступ запрещён.")
        return
    
    await message.answer("👑 *Админ панель*", reply_markup=admin_keyboard(), parse_mode="Markdown")

@dp.callback_query(lambda c: c.data == "admin_give_sub")
async def admin_give_sub_prompt(callback: CallbackQuery, state: FSMContext):
    if not is_owner(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён")
        return
    
    await callback.message.edit_text(
        "👑 *Выдача подписки*\n\n"
        "Отправь ID пользователя или username (без @):\n"
        "Для отмены /cancel",
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
        await message.answer(f"❌ Пользователь не найден.")
        await state.clear()
        return
    
    expiry_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    update_user_data(target_user_id, {"subscription_until": expiry_date})
    
    await message.answer(f"✅ *Подписка выдана до {expiry_date}*", parse_mode="Markdown")
    
    try:
        await bot.send_message(
            target_user_id,
            f"🎉 *Вам выдана премиум подписка до {expiry_date}!*\n\n📸 Отправляйте фото — я решу любые задачи!",
            parse_mode="Markdown"
        )
    except:
        pass
    
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
    
    stats_text = f"""📊 *Статистика*

👥 Пользователей: {total_users}
💎 Активных подписок: {active_subs}
📝 Запросов сегодня: {total_requests_today}
📈 Всего запросов: {total_requests_all}
🧠 Активных диалогов: {len(chat_histories)}"""
    
    await callback.message.edit_text(stats_text, parse_mode="Markdown")
    await callback.answer()

@dp.message(Command("cancel"))
async def cancel_admin(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Отменено", reply_markup=get_main_keyboard(message.from_user.id))

# ========== ОСНОВНОЙ ОБРАБОТЧИК ФОТО ==========
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
    thinking_msg = await message.answer("🔍 *Распознаю текст с фото через OCR...*", parse_mode="Markdown")
    
    try:
        model = user_models.get(user_id, DEFAULT_MODEL)
        model_name = MODELS.get(model, "")
        
        # Обрабатываем фото через OCR + выбранную модель
        answer, used_model = await process_photo_with_model(photo.file_id, user_question, model)
        
        if not answer:
            await thinking_msg.edit_text("⚠️ *Не удалось распознать текст с фото.*\n\nПопробуй:\n1. Сделать фото чётче\n2. Написать задачу текстом", parse_mode="Markdown")
            return
        
        if not has_active_subscription(user_id):
            increment_request(user_id)
        
        add_to_history(user_id, "user", f"[Фото] {user_question}")
        add_to_history(user_id, "assistant", answer[:500])
        
        await thinking_msg.delete()
        
        answer_parts = smart_split_text(answer)
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

# ========== ОБРАБОТЧИК ТЕКСТА ==========
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
        model = user_models.get(user_id, DEFAULT_MODEL)
        model_name = MODELS.get(model, "")
        
        answer, used_model = await ask_groq_text(user_id, question, model)
        
        add_to_history(user_id, "user", question[:500])
        add_to_history(user_id, "assistant", answer[:500])
        
        await thinking_msg.delete()
        
        answer_parts = smart_split_text(answer)
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
    print("🤖 AI-АССИСТЕНТ С РАСПОЗНАВАНИЕМ ФОТО")
    print("=" * 60)
    print(f"👑 Владелец: {OWNER_ID}")
    print(f"💰 Подписка: {STAR_PRICE} звёзд/месяц")
    print(f"🎁 Бесплатно: 20 запросов/день")
    print(f"📸 Модели: Llama 70B, Llama 8B (обе с OCR фото)")
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
        else:
            print("⚠️ Tesseract не найден. Установите: sudo apt-get install tesseract-ocr tesseract-ocr-rus")
    except:
        print("⚠️ Tesseract не найден. Установите: sudo apt-get install tesseract-ocr tesseract-ocr-rus")
    
    print("=" * 60)
    print("✅ БОТ ГОТОВ К РАБОТЕ!")
    print("📌 Отправляй фото с уравнениями — я распознаю и решу!")
    print("=" * 60)
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
