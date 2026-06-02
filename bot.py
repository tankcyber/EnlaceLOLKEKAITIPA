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
from aiogram.exceptions import TelegramBadRequest
from collections import defaultdict
from typing import Tuple, Optional

# ========== КОНФИГУРАЦИЯ ==========
GROQ_API_KEY = "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"
OPENROUTER_API_KEY = "sk-or-v1-ваш_ключ_от_openrouter"  # Вставьте сюда ваш ключ!
OWNER_ID = 5439940299
STAR_PRICE = 30

DATA_FILE = "users_data.json"
HISTORY_FILE = "chat_history.json"
MAX_HISTORY_LENGTH = 15

# ========== ВСЕ БЕСПЛАТНЫЕ МОДЕЛИ GROQ ==========
MODELS = {
    "llama-3.3-70b-versatile": "🦙 Llama 70B (мощная)",
    "llama-3.1-8b-instant": "⚡ Llama 8B (быстрая)",
    "meta-llama/llama-4-scout-17b-16e-instruct": "👁️ Llama 4 Scout (анализ фото!)",
    "qwen/qwen3-32b": "🚀 Qwen 3 32B (высокий лимит)",
    "openai/gpt-oss-120b": "🏛️ GPT-OSS 120B (мощная)",
    "groq/compound": "💻 Compound (кодинг)",
    # ----- OPENROUTER (бесплатные модели, через ваш ключ OpenRouter) -----
    "nvidia/nemotron-3-super": "🔷 Nemotron 3 Super (1M контекст)",
    "deepseek/deepseek-v4-flash": "🐋 DeepSeek V4 Flash (284B параметров)",
    "google/gemma-4-31b-it": "🌟 Gemma 4 31B (мультимодальная)",
    "nvidia/nemotron-nano-2-vl": "📹 Nemotron Nano 2 VL (видео+OCR)",
    "inclusionai/ling-2.6-1t": "🧠 Ling-2.6-1T (триллион параметров!)",
}

DEFAULT_MODEL = "llama-3.3-70b-versatile"
FAST_MODEL = "llama-3.1-8b-instant"
VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

bot = Bot(
    token="8857441987:AAFxXSTX1fOiksCuymGDNerV3NNdEeV9Wx4",
    default=DefaultBotProperties(parse_mode="Markdown")
)

dp = Dispatcher(storage=MemoryStorage())
user_models = {}
chat_histories = defaultdict(list)

# ========== OPENROUTER API (БЕСПЛАТНЫЕ МОДЕЛИ) ==========
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

async def ask_openrouter(question: str, model: str, system_prompt: str = None, image_base64: str = None) -> str:
    """Запрос к OpenRouter (бесплатные модели)"""
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://t.me/your_bot",
        "X-Title": "AI Assistant Bot"
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
                    return "⏰ Лимит запросов OpenRouter. Попробуй через минуту."
                else:
                    return f"❌ OpenRouter ошибка: {resp.status}"
        except Exception as e:
            return f"⚠️ Ошибка OpenRouter: {str(e)}"

# ========== ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ ДЛЯ УДАЛЕНИЯ ==========
async def safe_delete_message(message):
    if message is None:
        return
    try:
        await message.delete()
    except TelegramBadRequest:
        pass
    except Exception:
        pass

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

# ========== OCR ЧЕРЕЗ БЕСПЛАТНЫЙ API (НЕ ТРЕБУЕТ TESSERACT) ==========
async def extract_text_from_photo_api(photo_file_id: str) -> str:
    """Извлекает текст с фото через бесплатный OCR.space API"""
    try:
        # Скачиваем фото
        file = await bot.get_file(photo_file_id)
        file_bytes = await bot.download_file(file.file_path)
        image_base64 = base64.b64encode(file_bytes.getvalue()).decode('utf-8')
        
        # Бесплатный OCR API (25000 запросов/месяц)
        async with aiohttp.ClientSession() as session:
            data = {
                'base64Image': f'data:image/jpeg;base64,{image_base64}',
                'apikey': 'helloworld',  # Бесплатный ключ для тестов
                'language': 'rus',
                'isOverlayRequired': 'false',
                'OCREngine': '2'  # Движок 2 лучше для математики
            }
            
            async with session.post('https://api.ocr.space/parse/image', data=data, timeout=30) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    if not result.get('IsErroredOnProcessing'):
                        parsed_text = result.get('ParsedResults', [{}])[0].get('ParsedText', '')
                        if parsed_text and parsed_text.strip():
                            # Очистка текста
                            text = parsed_text.strip()
                            text = re.sub(r'(\d+)\s*/\s*(\d+)', r'\1/\2', text)
                            text = re.sub(r'(\d+)\s*=\s*(\d+)', r'\1=\2', text)
                            return text
        return ""
        
    except Exception as e:
        print(f"❌ OCR API ошибка: {e}")
        return ""

# ========== АНАЛИЗ ФОТО ЧЕРЕЗ LLAMA 4 SCOUT ==========
async def analyze_photo_with_vision(image_base64: str, user_question: str) -> str:
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": VISION_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": f"Ты — репетитор по математике. Реши задачу с этого изображения. Если видишь уравнение — реши пошагово. Ответь на русском.\n\nВопрос: {user_question}"
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
                    return None
        except Exception as e:
            print(f"❌ Llama 4 Scout ошибка: {e}")
            return None

# ========== ОБРАБОТКА ФОТО ЧЕРЕЗ OCR API + МОДЕЛЬ ==========
async def process_photo_with_ocr_api(photo_file_id: str, user_question: str, model: str) -> Tuple[Optional[str], str]:
    """Распознаёт текст через OCR API, затем отправляет в модель"""
    extracted_text = await extract_text_from_photo_api(photo_file_id)
    
    if not extracted_text:
        return None, model
    
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    
    prompt = f"""📸 ПОЛЬЗОВАТЕЛЬ ОТПРАВИЛ ФОТО

Вот текст, который удалось распознать с фото:
{extracted_text}

Вопрос пользователя: {user_question}

Реши задачу. Если это уравнение — реши пошагово. Ответь на русском языке."""
    
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
                    preview = extracted_text[:400] + "..." if len(extracted_text) > 400 else extracted_text
                    full_answer = f"📝 *Распознано с фото:*\n```\n{preview}\n```\n\n{answer}"
                    return full_answer, model
                else:
                    return None, model
        except Exception as e:
            print(f"❌ Ошибка: {e}")
            return None, model

# ========== УНИВЕРСАЛЬНЫЙ ОБРАБОТЧИК ФОТО ==========
async def process_photo(photo_file_id: str, user_question: str, model: str) -> Tuple[str, str]:
    # Пробуем Llama 4 Scout если он выбран
    if model == VISION_MODEL:
        file = await bot.get_file(photo_file_id)
        file_bytes = await bot.download_file(file.file_path)
        image_base64 = base64.b64encode(file_bytes.getvalue()).decode('utf-8')
        
        answer = await analyze_photo_with_vision(image_base64, user_question)
        if answer:
            return answer, VISION_MODEL
    
    # Резерв: OCR API + выбранная модель
    result = await process_photo_with_ocr_api(photo_file_id, user_question, model)
    if result[0]:
        return result
    
    # Если всё failed
    return "❌ Не удалось распознать текст с фото.\n\nПопробуй:\n1. Отправить фото с лучшим освещением\n2. Чётко сфотографировать уравнение\n3. Написать задачу текстом", model

# ========== ТЕКСТОВЫЙ ЗАПРОС ==========
async def ask_groq_text(user_id: int, question: str, model: str) -> Tuple[str, str]:
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
                    error_text = await resp.text()
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

def get_context_messages(user_id: int, max_messages: int = 6) -> list:
    user_id_str = str(user_id)
    if user_id_str not in chat_histories:
        chat_histories[user_id_str] = []
    return chat_histories[user_id_str][-max_messages:]

def add_to_history(user_id: int, role: str, content: str):
    user_id_str = str(user_id)
    if user_id_str not in chat_histories:
        chat_histories[user_id_str] = []
    chat_histories[user_id_str].append({"role": role, "content": content[:1000]})
    if len(chat_histories[user_id_str]) > MAX_HISTORY_LENGTH * 2:
        chat_histories[user_id_str].pop(0)

def clear_history(user_id: int):
    user_id_str = str(user_id)
    chat_histories[user_id_str] = []

def get_user_data(user_id: int) -> dict:
    data = {}
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
    
    user_id_str = str(user_id)
    if user_id_str not in data:
        data[user_id_str] = {
            "requests_today": 0,
            "last_reset": datetime.now().strftime("%Y-%m-%d"),
            "username": None,
            "total_requests": 0,
            "subscription_until": None
        }
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    return data[user_id_str]

def update_user_data(user_id: int, updates: dict):
    data = {}
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
    
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
    
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def reset_daily_requests(user_id: int):
    user_data = get_user_data(user_id)
    today = datetime.now().strftime("%Y-%m-%d")
    if user_data["last_reset"] != today:
        update_user_data(user_id, {"requests_today": 0, "last_reset": today})
        return True
    return False

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
        sub_until = get_user_data(user_id).get("subscription_until")
        welcome_msg = f"""🌟 *Добро пожаловать!*

💎 *Премиум подписка до {sub_until}*

✅ Безлимитные запросы
✅ Анализ фото через Llama 4 Scout
✅ 6+ бесплатных моделей AI

Отправь фото с уравнением или напиши вопрос!"""
    else:
        welcome_msg = f"""🌟 *Добро пожаловать в AI-ассистент!*

🎁 *Бесплатно:* {remaining}/20 запросов в день

📸 *Отправь фото с уравнением* — я распознаю и решу!
🧠 *Память диалога* — помню контекст
🚀 *6+ моделей AI* на выбор

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
        sub_until = get_user_data(user_id).get("subscription_until")
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
        f"• Анализ фото через Llama 4 Scout\n"
        f"• Память диалога\n\n"
        f"👤 *Владелец:* @SedoyDiada",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(message.from_user.id)
    )

@dp.message(lambda message: message.text == "🧠 Выбрать модель")
async def change_model_button(message: Message):
    text = "🧠 *Выбери модель AI:*\n\n"
    for model_id, model_name in MODELS.items():
        if model_id == VISION_MODEL:
            text += f"👁️ **{model_name}** — анализирует фото!\n"
        else:
            text += f"• **{model_name}**\n"
    text += "\n💡 Все модели БЕСПЛАТНЫ!"
    await message.answer(text, reply_markup=model_choice_keyboard(), parse_mode="Markdown")

@dp.message(lambda message: message.text == "❓ Помощь")
async def help_button(message: Message):
    help_text = """❓ *Как пользоваться ботом*

📸 *Фото с задачами:*
• Отправь фото с уравнением
• Llama 4 Scout проанализирует и решит
• Другие модели тоже работают с фото через OCR

📝 *Текст:* просто напиши вопрос
• x² - 5x + 6 = 0
• Найди производную x³+2x²

🎁 *Тарифы:*
• Бесплатно: 20 запросов/день
• Премиум: 30⭐/месяц — безлимит"""
    
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
        "Отправь ID пользователя:\nДля отмены /cancel",
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
    
    if not user_input.isdigit():
        await message.answer("❌ Нужно отправить числовой ID пользователя")
        await state.clear()
        return
    
    target_user_id = int(user_input)
    expiry_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    update_user_data(target_user_id, {"subscription_until": expiry_date})
    
    await message.answer(f"✅ *Подписка выдана до {expiry_date}*", parse_mode="Markdown")
    
    try:
        await bot.send_message(
            target_user_id,
            f"🎉 *Вам выдана премиум подписка до {expiry_date}!*",
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
    
    if not os.path.exists(DATA_FILE):
        await callback.message.edit_text("📊 Нет данных")
        await callback.answer()
        return
    
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        users_data = json.load(f)
    
    total_users = len(users_data)
    active_subs = 0
    total_requests_today = 0
    today = datetime.now().strftime("%Y-%m-%d")
    
    for uid, data in users_data.items():
        sub_until = data.get("subscription_until")
        if sub_until:
            try:
                if datetime.strptime(sub_until, "%Y-%m-%d") > datetime.now():
                    active_subs += 1
            except:
                pass
        
        if data.get("last_reset") == today:
            total_requests_today += data.get("requests_today", 0)
    
    stats_text = f"""📊 *Статистика*

👥 Пользователей: {total_users}
💎 Активных подписок: {active_subs}
📝 Запросов сегодня: {total_requests_today}
🚀 Моделей: {len(MODELS)}"""
    
    await callback.message.edit_text(stats_text, parse_mode="Markdown")
    await callback.answer()

@dp.message(Command("cancel"))
async def cancel_admin(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Отменено", reply_markup=get_main_keyboard(message.from_user.id))

# ========== ОБРАБОТЧИК ФОТО ==========
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
    
    model = user_models.get(user_id, DEFAULT_MODEL)
    thinking_msg = await message.answer("🔍 *Анализирую фото...*", parse_mode="Markdown")
    
    try:
        answer, used_model = await process_photo(photo.file_id, user_question, model)
        
        if not has_active_subscription(user_id):
            increment_request(user_id)
        
        add_to_history(user_id, "user", f"[Фото] {user_question}")
        add_to_history(user_id, "assistant", answer[:500])
        
        await safe_delete_message(thinking_msg)
        
        answer_parts = smart_split_text(answer)
        used_model_name = MODELS.get(used_model, "")
        
        for i, part in enumerate(answer_parts):
            footer = f"\n\n— {used_model_name}" if i == len(answer_parts)-1 and used_model_name else ""
            await message.answer(part + footer, parse_mode="Markdown")
        
        if not has_active_subscription(user_id):
            remaining = get_remaining_free_requests(user_id)
            if isinstance(remaining, int) and remaining <= 5:
                await message.answer(f"⚠️ *Осталось {remaining} запросов на сегодня*", parse_mode="Markdown")
                
    except Exception as e:
        await safe_delete_message(thinking_msg)
        await message.answer(f"❌ Ошибка: {str(e)[:200]}", reply_markup=get_main_keyboard(user_id))

# ========== ОБРАБОТЧИК ТЕКСТА ==========
@dp.message(ChatState.waiting_for_question)
async def handle_text(message: Message):
    question = message.text.strip()
    
    menu_buttons = ["📊 Статус", "💎 Купить подписку", "🧠 Выбрать модель", 
                    "🔄 Сбросить диалог", "❓ Помощь"]
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
        
        await safe_delete_message(thinking_msg)
        
        answer_parts = smart_split_text(answer)
        
        for i, part in enumerate(answer_parts):
            footer = f"\n\n— {model_name}" if i == len(answer_parts)-1 and model_name else ""
            await message.answer(part + footer, parse_mode="Markdown")
        
        if not has_active_subscription(user_id):
            remaining = get_remaining_free_requests(user_id)
            if isinstance(remaining, int) and remaining <= 5:
                await message.answer(f"⚠️ *Осталось {remaining} запросов на сегодня*", parse_mode="Markdown")
            
    except Exception as e:
        await safe_delete_message(thinking_msg)
        await message.answer(f"❌ Ошибка: {str(e)[:200]}", reply_markup=get_main_keyboard(user_id))

# ========== ЗАПУСК ==========
async def main():
    print("=" * 60)
    print("🤖 AI-АССИСТЕНТ (OCR через API)")
    print("=" * 60)
    print(f"👑 Владелец: {OWNER_ID}")
    print(f"📸 OCR: Бесплатный API (не требует Tesseract)")
    print(f"🚀 Модели: {len(MODELS)}")
    print("=" * 60)
    
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump({}, f)
        print("📁 Создан users_data.json")
    
    print("=" * 60)
    print("✅ БОТ ГОТОВ!")
    print("📌 Отправляй фото — распознаю через API!")
    print("=" * 60)
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
