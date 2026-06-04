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
from typing import Tuple, Optional, Dict, List

# ========== КОНФИГУРАЦИЯ ==========
GROQ_API_KEY = "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"
OPENROUTER_API_KEY = "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"
GEMINI_API_KEY = "AQ.Ab8RN6L3sRuYrqAmAuFWtjA_avAIAwmN3cXBe8fDO1gem3mBHQ"  # Получить: https://aistudio.google.com/
OWNER_ID = 5439940299
STAR_PRICE = 30

DATA_FILE = "users_data.json"
HISTORY_FILE = "chat_history.json"
MAX_HISTORY_LENGTH = 15

# ========== ВСЕ МОДЕЛИ ПО КАТЕГОРИЯМ ==========
MODELS_BY_CATEGORY = {
    "code": {
        "name": "💻 Код и программирование",
        "emoji": "💻",
        "models": {
            "groq/compound": "Compound (кодинг + поиск)",
            "groq/compound-mini": "Compound Mini (быстрый кодинг)",
            "openai/gpt-oss-120b": "GPT-OSS 120B (сложный код)",
            "openai/gpt-oss-20b": "GPT-OSS 20B (лёгкий код, быстрый)",
            "qwen/qwen3-32b": "Qwen 3 32B (универсальный код)",
        }
    },
    "vision": {
        "name": "👁️ Анализ изображений",
        "emoji": "👁️",
        "models": {
            "meta-llama/llama-4-scout-17b-16e-instruct": "Llama 4 Scout (анализ фото, 750 t/s)",
        }
    },
    "universal": {
        "name": "🌟 Универсальные",
        "emoji": "🌟",
        "models": {
            "llama-3.3-70b-versatile": "Llama 3.3 70B (мощная, 280 t/s)",
            "llama-3.1-8b-instant": "Llama 3.1 8B (быстрая, 560 t/s)",
            "gemini-2.0-flash": "⚡ Gemini 2.0 Flash (бесплатно, 1500/день)",
            "gemini-2.5-pro-exp": "🧠 Gemini 2.5 Pro (сложные задачи, 25/день)",
            "gemma-4-31b-it": "🟢 Gemma 4 31B (бесплатно, 1500/день)",
        }
    },
    "fast": {
        "name": "⚡ Быстрые",
        "emoji": "⚡",
        "models": {
            "openai/gpt-oss-20b": "GPT-OSS 20B (1000 t/s)",
            "llama-3.1-8b-instant": "Llama 3.1 8B (560 t/s)",
            "groq/compound-mini": "Compound Mini (450 t/s)",
            "gemini-2.0-flash": "Gemini 2.0 Flash (быстрый)",
        }
    },
    "math": {
        "name": "🧮 Математика и логика",
        "emoji": "🧮",
        "models": {
            "qwen/qwq-32b": "Qwen QWQ 32B (решение задач)",
            "llama-3.3-70b-versatile": "Llama 70B (сложные расчёты)",
            "gemini-2.5-pro-exp": "Gemini 2.5 Pro (логика)",
        }
    }
}

# Полный плоский список для быстрого доступа
MODELS = {}
for category in MODELS_BY_CATEGORY.values():
    MODELS.update(category["models"])

DEFAULT_MODEL = "llama-3.3-70b-versatile"
VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

# API endpoints
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

bot = Bot(
    token="8857441987:AAFxXSTX1fOiksCuymGDNerV3NNdEeV9Wx4",
    default=DefaultBotProperties(parse_mode="Markdown")
)

dp = Dispatcher(storage=MemoryStorage())
user_models = {}
chat_histories = defaultdict(list)
# Словарь для отслеживания последнего сообщения бота для каждого пользователя
user_last_bot_message = {}

# ========== GEMINI API (БЕСПЛАТНЫЙ) ==========
try:
    from google import genai
    from google.genai import types
    GEMINI_AVAILABLE = True
except ImportError:
    print("⚠️ Библиотека google-genai не установлена. Установи: pip install google-genai")
    GEMINI_AVAILABLE = False

class AsyncGeminiClient:
    def __init__(self, model: str = "gemini-2.0-flash"):
        self.client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_AVAILABLE else None
        self.model = model
    
    async def generate(self, prompt: str, image_base64: str = None) -> str:
        if not self.client:
            return "❌ Gemini не настроен. Установи google-genai"
        
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self._sync_generate,
            prompt,
            image_base64
        )
    
    def _sync_generate(self, prompt: str, image_base64: str = None) -> str:
        try:
            if image_base64:
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=[
                        prompt,
                        types.Part.from_bytes(
                            data=base64.b64decode(image_base64),
                            mime_type="image/jpeg"
                        )
                    ]
                )
            else:
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=prompt
                )
            return response.text if response.text else "❌ Пустой ответ от Gemini"
        except Exception as e:
            error_str = str(e)
            if "429" in error_str:
                return "⏰ Лимит Gemini на сегодня исчерпан (1500/день). Завтра снова будет доступно!"
            return f"❌ Gemini ошибка: {error_str[:100]}"

# ========== КОНВЕРТАЦИЯ LATEX ДЛЯ TELEGRAM ==========
def convert_latex_to_telegram(text: str) -> str:
    """Конвертирует LaTeX формулы в формат Telegram Markdown"""
    if not text:
        return text
    
    def replace_double_dollars(match):
        formula = match.group(1).strip()
        formula = formula.replace('\n', '\n')
        return f'\n```latex\n{formula}\n```\n'
    
    def replace_single_dollars(match):
        formula = match.group(1).strip()
        return f'`${formula}$`'
    
    try:
        text = re.sub(r'\$\$(.*?)\$\$', replace_double_dollars, text, flags=re.DOTALL)
        text = re.sub(r'\$(.*?)\$', replace_single_dollars, text)
        text = re.sub(r'^#+\s+(.+?)$', r'*\1*', text, flags=re.MULTILINE)
        return text
    except Exception as e:
        print(f"Ошибка конвертации LaTeX: {e}")
        return text

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

# ========== УНИВЕРСАЛЬНЫЙ СИСТЕМНЫЙ ПРОМПТ ==========
SYSTEM_PROMPT = """Ты — полезный AI-ассистент. Отвечай на вопросы пользователя дружелюбно и по делу.

ПРАВИЛА ФОРМАТИРОВАНИЯ:
- Используй Markdown для форматирования
- Для формул используй $$формула$$ (они будут красиво отображаться)
- Код в блоках ```language
- Отвечай на том же языке, на котором задан вопрос

Будь полезным и следуй инструкциям пользователя."""

# ========== OCR ЧЕРЕЗ БЕСПЛАТНЫЙ API ==========
async def extract_text_from_photo_api(photo_file_id: str) -> str:
    """Извлекает текст с фото через бесплатный OCR.space API"""
    try:
        file = await bot.get_file(photo_file_id)
        file_bytes = await bot.download_file(file.file_path)
        image_base64 = base64.b64encode(file_bytes.getvalue()).decode('utf-8')
        
        async with aiohttp.ClientSession() as session:
            data = {
                'base64Image': f'data:image/jpeg;base64,{image_base64}',
                'apikey': 'helloworld',
                'language': 'rus',
                'isOverlayRequired': 'false',
                'OCREngine': '2'
            }
            
            async with session.post('https://api.ocr.space/parse/image', data=data, timeout=30) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    if not result.get('IsErroredOnProcessing'):
                        parsed_text = result.get('ParsedResults', [{}])[0].get('ParsedText', '')
                        if parsed_text and parsed_text.strip():
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
                        "text": f"Ответь на вопрос пользователя, используя информацию с изображения.\n\nВопрос: {user_question}"
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}
                    }
                ]
            }
        ],
        "max_tokens": 2500,
        "temperature": 0.7
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(GROQ_API_URL, headers=headers, json=payload, timeout=90) as resp:
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
    
    prompt = f"""Пользователь отправил фото. Распознанный текст с фото:
{extracted_text}

Вопрос пользователя: {user_question}

Ответь на вопрос, используя распознанный текст с фото."""
    
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 2500,
        "temperature": 0.7
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(GROQ_API_URL, headers=headers, json=payload, timeout=90) as resp:
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
    
    return "❌ Не удалось распознать текст с фото.\n\nПопробуй отправить фото с лучшим качеством или напиши вопрос текстом.", model

# ========== ТЕКСТОВЫЙ ЗАПРОС (GROQ) ==========
async def ask_groq_text(user_id: int, question: str, model: str) -> Tuple[str, str]:
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    
    context = get_context_messages(user_id, max_messages=6)
    
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for msg in context[-4:]:
        messages.append(msg)
    messages.append({"role": "user", "content": question})
    
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 6000
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(GROQ_API_URL, headers=headers, json=payload, timeout=120) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    answer = data["choices"][0]["message"]["content"]
                    
                    if len(answer) > 10000:
                        answer = answer[:10000] + "\n\n[Ответ сокращён из-за длины...]"
                    return answer, model
                elif resp.status == 429:
                    return "⏰ *Лимит API Groq!* Попробуй другую модель или подожди минуту.", model
                else:
                    return f"❌ Ошибка API: {resp.status}", model
        except asyncio.TimeoutError:
            return "⏰ *Превышено время ожидания.* Попробуй разбить запрос на части.", model
        except Exception as e:
            return f"⚠️ Ошибка: {str(e)}", model

# ========== ТЕКСТОВЫЙ ЗАПРОС (GEMINI) ==========
async def ask_gemini_text(question: str, model: str, image_base64: str = None) -> Tuple[str, str]:
    """Запрос к Gemini API"""
    if not GEMINI_AVAILABLE:
        return "❌ Gemini не настроен. Установи библиотеку: pip install google-genai", model
    
    gemini = AsyncGeminiClient(model=model)
    answer = await gemini.generate(question, image_base64)
    return answer, model

# ========== УНИВЕРСАЛЬНЫЙ ЗАПРОС ==========
async def ask_ai(user_id: int, question: str, model: str, image_base64: str = None) -> Tuple[str, str]:
    """Маршрутизация запросов к нужному API"""
    
    # Gemini модели
    if model.startswith("gemini-") or model.startswith("gemma-"):
        return await ask_gemini_text(question, model, image_base64)
    
    # Groq модели
    else:
        return await ask_groq_text(user_id, question, model)

# ========== ОТПРАВКА ДЛИННЫХ СООБЩЕНИЙ ==========
async def send_long_message(message: Message, text: str, model_name: str = ""):
    """Отправляет длинный текст частями, конвертируя формулы для Telegram"""
    if not text or text == "None":
        await message.answer("❌ Пустой ответ", parse_mode="Markdown")
        return
    
    converted_text = convert_latex_to_telegram(text)
    
    if len(converted_text) <= 4000:
        footer = f"\n\n— {model_name}" if model_name else ""
        try:
            msg = await message.answer(converted_text + footer, parse_mode="Markdown")
            user_last_bot_message[message.from_user.id] = msg
        except Exception:
            msg = await message.answer(converted_text + footer.replace("*", "").replace("_", ""), parse_mode=None)
            user_last_bot_message[message.from_user.id] = msg
        return
    
    parts = []
    current_part = ""
    
    code_blocks = converted_text.split('```')
    for i, block in enumerate(code_blocks):
        if i % 2 == 0:
            if len(current_part) + len(block) < 3500:
                current_part += block
            else:
                if current_part:
                    parts.append(current_part)
                current_part = block
        else:
            if len(current_part) + len(block) + 6 < 3500:
                current_part += f'```{block}```'
            else:
                if current_part:
                    parts.append(current_part)
                current_part = f'```{block}```'
    
    if current_part:
        parts.append(current_part)
    
    if len(parts) == 1 and len(parts[0]) > 4000:
        parts = []
        for i in range(0, len(converted_text), 3500):
            parts.append(converted_text[i:i+3500])
    
    for i, part in enumerate(parts):
        footer = ""
        if i == len(parts)-1 and model_name:
            footer = f"\n\n— {model_name}"
        if len(parts) > 1:
            footer += f"\n\n*Часть {i+1}/{len(parts)}*"
        
        try:
            msg = await message.answer(part + footer, parse_mode="Markdown")
            user_last_bot_message[message.from_user.id] = msg
            await asyncio.sleep(0.5)
        except Exception:
            try:
                msg = await message.answer(part + footer.replace("*", "").replace("_", ""), parse_mode=None)
                user_last_bot_message[message.from_user.id] = msg
            except:
                await message.answer("❌ Ошибка при отправке сообщения")
            await asyncio.sleep(0.5)

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def get_context_messages(user_id: int, max_messages: int = 6) -> list:
    user_id_str = str(user_id)
    if user_id_str not in chat_histories:
        chat_histories[user_id_str] = []
    return chat_histories[user_id_str][-max_messages:]

def add_to_history(user_id: int, role: str, content: str):
    user_id_str = str(user_id)
    if user_id_str not in chat_histories:
        chat_histories[user_id_str] = []
    chat_histories[user_id_str].append({"role": role, "content": content[:2000]})
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
            "subscription_until": None,
            "current_model": DEFAULT_MODEL  # Сохраняем выбранную модель пользователя
        }
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    # Восстанавливаем выбранную модель пользователя
    if user_id_str in data and "current_model" in data[user_id_str]:
        user_models[user_id] = data[user_id_str]["current_model"]
    else:
        user_models[user_id] = DEFAULT_MODEL
    
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
            "subscription_until": None,
            "current_model": DEFAULT_MODEL
        }
    data[user_id_str].update(updates)
    
    # Если обновляется модель, сохраняем её в отдельном поле
    if "current_model" in updates:
        data[user_id_str]["current_model"] = updates["current_model"]
    
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

# ========== КЛАВИАТУРЫ ДЛЯ МОДЕЛЕЙ ==========
def get_model_categories_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура с категориями моделей"""
    buttons = []
    for category_id, category in MODELS_BY_CATEGORY.items():
        buttons.append([InlineKeyboardButton(
            text=f"{category['emoji']} {category['name']}", 
            callback_data=f"cat_{category_id}"
        )])
    buttons.append([InlineKeyboardButton(text="❌ Закрыть", callback_data="close")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_models_by_category_keyboard(category_id: str, current_page: int = 0, items_per_page: int = 5) -> InlineKeyboardMarkup:
    """Клавиатура с моделями выбранной категории"""
    category = MODELS_BY_CATEGORY.get(category_id)
    if not category:
        return get_model_categories_keyboard()
    
    models_list = list(category["models"].items())
    total_pages = (len(models_list) + items_per_page - 1) // items_per_page
    
    start = current_page * items_per_page
    end = start + items_per_page
    current_models = models_list[start:end]
    
    buttons = []
    for model_id, model_desc in current_models:
        buttons.append([InlineKeyboardButton(
            text=f"🤖 {model_desc[:30]}", 
            callback_data=f"model_{model_id}"
        )])
    
    nav_buttons = []
    if current_page > 0:
        nav_buttons.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"page_{category_id}_{current_page-1}"))
    if current_page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="Вперёд ▶️", callback_data=f"page_{category_id}_{current_page+1}"))
    
    if nav_buttons:
        buttons.append(nav_buttons)
    
    buttons.append([
        InlineKeyboardButton(text="🏠 Все категории", callback_data="back_to_categories"),
        InlineKeyboardButton(text="❌ Закрыть", callback_data="close")
    ])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_current_model_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Клавиатура с информацией о текущей модели"""
    current_model = user_models.get(user_id, DEFAULT_MODEL)
    current_model_name = MODELS.get(current_model, "Неизвестно")
    
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🧠 Текущая: {current_model_name[:25]}", callback_data="current_model_info")],
        [InlineKeyboardButton(text="🔄 Сменить модель", callback_data="change_model_start")],
        [InlineKeyboardButton(text="❌ Закрыть", callback_data="close")]
    ])

# ========== ОСНОВНЫЕ КЛАВИАТУРЫ ==========
def get_main_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    remaining = get_remaining_free_requests(user_id)
    has_sub = has_active_subscription(user_id)
    
    # Получаем текущую модель пользователя
    current_model = user_models.get(user_id, DEFAULT_MODEL)
    model_short_name = MODELS.get(current_model, "Модель").split()[0]
    
    if has_sub:
        status_text = "💎 Премиум (безлимит)"
    else:
        status_text = f"🎫 Осталось: {remaining}/20"
    
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=f"📊 Статус | {status_text}")],
            [KeyboardButton(text="💎 Купить подписку"), KeyboardButton(text=f"🧠 {model_short_name}")],
            [KeyboardButton(text="🔄 Сбросить диалог"), KeyboardButton(text="❓ Помощь")]
        ],
        resize_keyboard=True
    )

def admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👑 Выдать подписку", callback_data="admin_give_sub")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="❌ Закрыть", callback_data="close")]
    ])

# ========== СОСТОЯНИЯ ==========
class AdminState(StatesGroup):
    waiting_for_user_id = State()

# Состояние по умолчанию всегда waiting_for_question, не нужно отдельно хранить

# ========== ОБРАБОТЧИКИ ==========
@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    
    # Загружаем данные пользователя (модель восстановится автоматически)
    get_user_data(user_id)
    
    username = message.from_user.username
    if username:
        update_user_data(user_id, {"username": username})
    
    remaining = get_remaining_free_requests(user_id)
    has_sub = has_active_subscription(user_id)
    current_model = user_models.get(user_id, DEFAULT_MODEL)
    model_name = MODELS.get(current_model, "Llama 70B")
    
    if has_sub:
        sub_until = get_user_data(user_id).get("subscription_until")
        welcome_msg = f"""🌟 *Добро пожаловать!*

💎 *Премиум подписка до {sub_until}*

✅ Безлимитные запросы
✅ 15+ моделей AI по категориям
✅ Gemini + Groq

🧠 *Текущая модель:* {model_name}

Отправь любой вопрос или фото!"""
    else:
        welcome_msg = f"""🌟 *Добро пожаловать в AI-ассистент!*

🎁 *Бесплатно:* {remaining}/20 запросов в день

📸 *Отправь фото* — я распознаю текст и отвечу
🧠 *15+ моделей AI по категориям:*
   💻 Для кода
   👁️ Для анализа фото
   🌟 Универсальные
   ⚡ Быстрые
   🧮 Для математики

💎 *Премиум за 30 звёзд:* безлимитные запросы

🧠 *Текущая модель:* {model_name}

Просто напиши вопрос или отправь фото!"""
    
    await message.answer(welcome_msg, reply_markup=get_main_keyboard(user_id), parse_mode="Markdown")

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
        f"• Анализ фото\n"
        f"• Все модели AI\n\n"
        f"👤 *Владелец:* @SedoyDiada",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(message.from_user.id)
    )

@dp.message(lambda message: message.text and message.text.startswith("🧠"))
async def change_model_button(message: Message):
    """Показывает категории моделей"""
    text = """🧠 *Выбери категорию модели AI:*

💻 **Код и программирование** — для написания кода, отладки
👁️ **Анализ изображений** — работа с фото, распознавание
🌟 **Универсальные** — всё в одном, лучший баланс
⚡ **Быстрые** — максимальная скорость ответа
🧮 **Математика и логика** — решение задач, расчёты

Нажми на категорию, чтобы увидеть модели:"""
    
    await message.answer(text, reply_markup=get_model_categories_keyboard(), parse_mode="Markdown")

@dp.message(lambda message: message.text == "❓ Помощь")
async def help_button(message: Message):
    help_text = """❓ *Как пользоваться ботом*

📸 *Фото:*
• Отправь фото с текстом или задачей
• ИИ распознает и ответит на вопрос

📝 *Текст:*
• Просто напиши любой вопрос

🧠 *Модели AI с категориями:*
• **💻 Код** — для программирования
• **👁️ Изображения** — анализ фото
• **🌟 Универсальные** — для всего
• **⚡ Быстрые** — максимальная скорость
• **🧮 Математика** — для расчётов

🎁 *Тарифы:*
• Бесплатно: 20 запросов/день
• Премиум: 30⭐/месяц — безлимит

💡 Чтобы сменить модель — нажми *🧠 Название_модели* в меню!"""
    
    await message.answer(help_text, parse_mode="Markdown", reply_markup=get_main_keyboard(message.from_user.id))

@dp.message(lambda message: message.text == "🔄 Сбросить диалог")
async def reset_button(message: Message):
    clear_history(message.from_user.id)
    await message.answer("🔄 *Диалог сброшен!*", parse_mode="Markdown", reply_markup=get_main_keyboard(message.from_user.id))

# ========== ОБРАБОТЧИКИ ИНЛАЙН-КНОПОК ДЛЯ МОДЕЛЕЙ ==========
@dp.callback_query(lambda c: c.data.startswith("cat_"))
async def process_category_selection(callback: CallbackQuery):
    """Обработка выбора категории моделей"""
    category_id = callback.data.replace("cat_", "")
    
    if category_id not in MODELS_BY_CATEGORY:
        await callback.answer("❌ Категория не найдена")
        return
    
    category = MODELS_BY_CATEGORY[category_id]
    text = f"{category['emoji']} *{category['name']}*\n\nВыбери модель:"
    
    await callback.message.edit_text(text, reply_markup=get_models_by_category_keyboard(category_id), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("page_"))
async def process_page_change(callback: CallbackQuery):
    """Обработка пагинации в списке моделей"""
    parts = callback.data.split("_")
    if len(parts) != 3:
        await callback.answer("❌ Ошибка")
        return
    _, category_id, page = parts
    page = int(page)
    
    category = MODELS_BY_CATEGORY.get(category_id)
    if not category:
        await callback.answer("❌ Категория не найдена")
        return
    
    text = f"{category['emoji']} *{category['name']}*\n\nВыбери модель:"
    
    await callback.message.edit_text(text, reply_markup=get_models_by_category_keyboard(category_id, page), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(lambda c: c.data == "back_to_categories")
async def back_to_categories(callback: CallbackQuery):
    """Возврат к списку категорий"""
    text = """🧠 *Выбери категорию модели AI:*

💻 **Код и программирование** — для написания кода
👁️ **Анализ изображений** — работа с фото
🌟 **Универсальные** — всё в одном
⚡ **Быстрые** — максимальная скорость
🧮 **Математика и логика** — решение задач

Нажми на категорию, чтобы увидеть модели:"""
    
    await callback.message.edit_text(text, reply_markup=get_model_categories_keyboard(), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(lambda c: c.data == "change_model_start")
async def change_model_start(callback: CallbackQuery):
    """Начало смены модели"""
    text = """🧠 *Выбери категорию модели AI:*

💻 **Код и программирование** — для написания кода
👁️ **Анализ изображений** — работа с фото
🌟 **Универсальные** — всё в одном
⚡ **Быстрые** — максимальная скорость
🧮 **Математика и логика** — решение задач

Нажми на категорию, чтобы увидеть модели:"""
    
    await callback.message.edit_text(text, reply_markup=get_model_categories_keyboard(), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("model_"))
async def process_model_choice(callback: CallbackQuery):
    """Выбор конкретной модели"""
    model_id = callback.data.replace("model_", "")
    
    if model_id not in MODELS:
        await callback.answer("❌ Модель не найдена")
        return
    
    user_id = callback.from_user.id
    user_models[user_id] = model_id
    
    # Сохраняем выбор в файл
    update_user_data(user_id, {"current_model": model_id})
    
    model_name = MODELS.get(model_id, "Неизвестно")
    
    await callback.message.edit_text(f"✅ *Модель изменена на {model_name}*", parse_mode="Markdown")
    await callback.message.answer("✨ Готов к работе!", reply_markup=get_main_keyboard(user_id))
    await callback.answer()

@dp.callback_query(lambda c: c.data == "current_model_info")
async def current_model_info(callback: CallbackQuery):
    """Информация о текущей модели"""
    user_id = callback.from_user.id
    model = user_models.get(user_id, DEFAULT_MODEL)
    model_name = MODELS.get(model, "Неизвестно")
    
    # Определяем категорию модели
    category_name = "Неизвестно"
    for cat_id, cat in MODELS_BY_CATEGORY.items():
        if model in cat["models"]:
            category_name = cat["name"]
            break
    
    info_text = f"""🧠 *Информация о модели*

**Модель:** {model_name}
**Категория:** {category_name}

💡 *Совет:* Если модель работает медленно или выдает ошибки, попробуй выбрать другую из той же категории."""
    
    await callback.message.answer(info_text, parse_mode="Markdown", reply_markup=get_current_model_keyboard(user_id))
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
@dp.message(lambda message: message.photo)
async def handle_photo(message: Message):
    user_id = message.from_user.id
    
    can_request, error_msg = can_make_request(user_id)
    if not can_request:
        await message.answer(error_msg, parse_mode="Markdown", reply_markup=get_main_keyboard(user_id))
        return
    
    photo = message.photo[-1]
    user_question = message.caption or "Что на этом фото? Ответь подробно."
    
    await bot.send_chat_action(message.chat.id, "typing")
    
    model = user_models.get(user_id, DEFAULT_MODEL)
    thinking_msg = await message.answer("🔍 *Анализирую фото...*", parse_mode="Markdown")
    
    try:
        file = await bot.get_file(photo.file_id)
        file_bytes = await bot.download_file(file.file_path)
        image_base64 = base64.b64encode(file_bytes.getvalue()).decode('utf-8')
        
        # Используем универсальную функцию ask_ai
        answer, used_model = await ask_ai(user_id, user_question, model, image_base64)
        
        if not has_active_subscription(user_id):
            increment_request(user_id)
        
        add_to_history(user_id, "user", f"[Фото] {user_question}")
        add_to_history(user_id, "assistant", answer[:500])
        
        await safe_delete_message(thinking_msg)
        
        used_model_name = MODELS.get(used_model, "")
        await send_long_message(message, answer, used_model_name)
        
        if not has_active_subscription(user_id):
            remaining = get_remaining_free_requests(user_id)
            if isinstance(remaining, int) and remaining <= 5:
                await message.answer(f"⚠️ *Осталось {remaining} запросов на сегодня*", parse_mode="Markdown")
                
    except Exception as e:
        await safe_delete_message(thinking_msg)
        await message.answer(f"❌ Ошибка: {str(e)[:200]}", reply_markup=get_main_keyboard(user_id))

# ========== ОБРАБОТЧИК ТЕКСТА ==========
@dp.message()
async def handle_text(message: Message):
    question = message.text.strip()
    
    # Пропускаем команды и кнопки меню
    menu_buttons = ["📊 Статус", "💎 Купить подписку", "❓ Помощь", "🔄 Сбросить диалог"]
    if any(question == btn or question.startswith("📊") or question.startswith("🧠") for btn in menu_buttons):
        return
    
    if not question:
        return
    
    user_id = message.from_user.id
    
    # Убеждаемся, что данные пользователя загружены
    get_user_data(user_id)
    
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
        
        answer, used_model = await ask_ai(user_id, question, model)
        
        add_to_history(user_id, "user", question[:500])
        add_to_history(user_id, "assistant", answer[:500])
        
        await safe_delete_message(thinking_msg)
        
        await send_long_message(message, answer, model_name)
        
        if not has_active_subscription(user_id):
            remaining = get_remaining_free_requests(user_id)
            if isinstance(remaining, int) and remaining <= 5:
                await message.answer(f"⚠️ *Осталось {remaining} запросов на сегодня*", parse_mode="Markdown")
            
    except Exception as e:
        await safe_delete_message(thinking_msg)
        await message.answer(f"❌ Ошибка: {str(e)[:200]}\n\nПопробуй перезапустить бота командой /start", reply_markup=get_main_keyboard(user_id))

# ========== ЗАПУСК ==========
async def main():
    print("=" * 60)
    print("🤖 AI-АССИСТЕНТ С КАТЕГОРИЯМИ МОДЕЛЕЙ")
    print("=" * 60)
    print(f"👑 Владелец: {OWNER_ID}")
    print(f"📸 OCR: Бесплатный API")
    print(f"🚀 Модели: {len(MODELS)}")
    print(f"🧠 Gemini: {'✅ Доступен' if GEMINI_AVAILABLE else '❌ Не установлен'}")
    print(f"🎯 Режим: Категорийный выбор моделей")
    print("=" * 60)
    
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump({}, f)
        print("📁 Создан users_data.json")
    
    print("=" * 60)
    print("✅ БОТ ГОТОВ!")
    print("📌 Пользователь может выбирать модели по категориям")
    print("📌 Выбранная модель сохраняется в файл")
    print("=" * 60)
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())