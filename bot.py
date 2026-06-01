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

DATA_FILE = "users_data.json"
HISTORY_FILE = "chat_history.json"
MAX_HISTORY_LENGTH = 15  # Уменьшил для производительности

# Умный выбор модели в зависимости от задачи
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
user_preferences = {}  # Хранение предпочтений пользователя
chat_histories = defaultdict(list)

# ========== СИСТЕМНЫЙ ПРОМПТ (ГИБРИДНЫЙ) ==========

HYBRID_SYSTEM_PROMPT = """Ты — универсальный AI-ассистент с расширенными возможностями.

ТВОИ ВОЗМОЖНОСТИ:

1. 📚 **ОБЩИЕ ЗНАНИЯ** - отвечай на любые вопросы из любой области
2. 🧮 **МАТЕМАТИКА** - решай уравнения, примеры, производные, интегралы, задачи
3. 💻 **ПРОГРАММИРОВАНИЕ** - пиши код, объясняй алгоритмы, отлаживай
4. 📝 **ПЕРЕВОД** - переводи с/на любые языки
5. 📖 **ТЕКСТОВЫЙ АНАЛИЗ** - анализируй, реферируй, пересказывай
6. ✍️ **КРЕАТИВ** - пиши стихи, рассказы, сценарии
7. 🔍 **ПОИСК** - подсказывай решения проблем

ПРАВИЛА ОТВЕТОВ:
- ВСЕГДА отвечай на русском, если вопрос не на другом языке
- Для длинных ответов разбивай на смысловые блоки (3-5 предложений)
- Если задача сложная - давай пошаговое решение
- Формулы оформляй в LaTeX: $$...$$ для отдельных, $...$ для встроенных
- Код оформляй в блоки ```language
- Будь дружелюбным и полезным
- Если вопрос непонятен - уточни

РАЗМЕР ОТВЕТА:
- На обычные вопросы: 2-4 абзаца
- На сложные: до 8 абзацев
- Избегай "воды" и повторений"""

# ========== ОБРАБОТКА ДЛИННЫХ ЗАПРОСОВ (СМАРТ-СПЛИТ) ==========

def smart_split_text(text: str, max_length: int = 3500) -> list:
    """Умное разбиение длинного текста на части"""
    if len(text) <= max_length:
        return [text]
    
    parts = []
    current_part = ""
    
    # Разбиваем по абзацам
    paragraphs = text.split('\n\n')
    
    for para in paragraphs:
        if len(current_part) + len(para) + 2 <= max_length:
            if current_part:
                current_part += '\n\n' + para
            else:
                current_part = para
        else:
            if current_part:
                parts.append(current_part)
                current_part = para
            else:
                # Если один абзац слишком длинный - режем по предложениям
                sentences = para.replace('!', '. ').replace('?', '. ').split('. ')
                temp_part = ""
                for sent in sentences:
                    if len(temp_part) + len(sent) + 2 <= max_length:
                        if temp_part:
                            temp_part += '. ' + sent
                        else:
                            temp_part = sent
                    else:
                        if temp_part:
                            parts.append(temp_part + '.')
                            temp_part = sent
                        else:
                            parts.append(sent[:max_length] + '...')
                            temp_part = ""
                if temp_part:
                    current_part = temp_part + '.'
    
    if current_part:
        parts.append(current_part)
    
    return parts

# ========== АВТОМАТИЧЕСКОЕ ОПРЕДЕЛЕНИЕ ТИПА ЗАДАЧИ ==========

def detect_task_type(text: str) -> dict:
    """
    Определяет тип задачи для выбора оптимальной модели и промпта
    """
    text_lower = text.lower()
    
    # Математика
    math_patterns = [
        r'[0-9\+\-\*\/\^=√∫∑∂]',  # Математические символы
        r'уравнени[ея]', r'реши', r'найди', r'вычисли',
        r'производн[аяую]', r'интеграл', r'функци[яю]',
        r'x\^?\d*', r'\d+[xyz]', r'[xyz]=', r'\+', r'-', r'\*', r'/'
    ]
    
    # Программирование
    code_patterns = [
        r'код', r'программ[ау]', r'функци[яю]', r'класс',
        r'python', r'javascript', r'java', r'c\+\+', r'html', r'css',
        r'бот', r'алгоритм', r'отладк[ау]', r'ошибк[ау]'
    ]
    
    # Перевод
    translate_patterns = [
        r'переведи', r'перевод', r'translate', r'как будет',
        r'на русском', r'на английском', r'на французском'
    ]
    
    # Анализ текста
    text_patterns = [
        r'проанализируй', r'сократи', r'перескажи', r'кратко',
        r'резюме', r'суть', r'главное', r'выдели'
    ]
    
    # Креатив
    creative_patterns = [
        r'напиши', r'сочини', r'стих', r'рассказ', r'историю',
        r'письмо', r'текст', r'описание'
    ]
    
    # Определяем основной тип
    is_math = any(re.search(p, text_lower) for p in math_patterns)
    is_code = any(re.search(p, text_lower) for p in code_patterns)
    is_translate = any(re.search(p, text_lower) for p in translate_patterns)
    is_text_analysis = any(re.search(p, text_lower) for p in text_patterns)
    is_creative = any(re.search(p, text_lower) for p in creative_patterns)
    
    return {
        'is_math': is_math,
        'is_code': is_code,
        'is_translate': is_translate,
        'is_text_analysis': is_text_analysis,
        'is_creative': is_creative,
        'use_fast_model': not is_math and not is_code and len(text) < 100  # Простые вопросы на быструю модель
    }

# ========== РАСШИРЕННЫЙ OCR С ПОДДЕРЖКОЙ ДРОБЕЙ ==========

async def extract_text_from_photo_advanced(photo_file_id: str) -> str:
    """
    Продвинутое распознавание текста с фото, включая дроби и формулы
    """
    try:
        file = await bot.get_file(photo_file_id)
        file_bytes = await bot.download_file(file.file_path)
        
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp_file:
            tmp_file.write(file_bytes.getvalue())
            tmp_path = tmp_file.name
        
        # Используем разные режимы Tesseract для лучшего распознавания
        # --psm 6: блок текста
        # --psm 13: raw line
        results = []
        
        # Режим 1: обычный текст
        result1 = subprocess.run(
            ['tesseract', tmp_path, 'stdout', '-l', 'rus+eng', '--psm', '6'],
            capture_output=True, text=True, timeout=30
        )
        if result1.returncode == 0 and result1.stdout.strip():
            results.append(result1.stdout.strip())
        
        # Режим 2: единая строка для формул
        result2 = subprocess.run(
            ['tesseract', tmp_path, 'stdout', '-l', 'eng', '--psm', '7'],
            capture_output=True, text=True, timeout=30
        )
        if result2.returncode == 0 and result2.stdout.strip():
            results.append(result2.stdout.strip())
        
        os.unlink(tmp_path)
        
        # Объединяем и чистим результат
        combined = ' '.join(results)
        
        # Нормализуем дроби (2/3 -> 2/3)
        combined = re.sub(r'(\d+)\s*/\s*(\d+)', r'\1/\2', combined)
        combined = re.sub(r'(\d+)\s*-\s*(\d+)', r'\1-\2', combined)
        combined = re.sub(r'(\d+)\s*\+\s*(\d+)', r'\1+\2', combined)
        combined = re.sub(r'(\d+)\s*\*\s*(\d+)', r'\1*\2', combined)
        
        if combined.strip():
            return combined.strip()
        return "Текст на фото не обнаружен"
        
    except Exception as e:
        print(f"❌ OCR ошибка: {e}")
        return "Текст на фото не обнаружен"

async def extract_text_alternative_api(photo_file_id: str) -> str:
    """Запасной OCR через API (для сложных формул)"""
    try:
        file = await bot.get_file(photo_file_id)
        file_bytes = await bot.download_file(file.file_path)
        image_base64 = base64.b64encode(file_bytes.getvalue()).decode('utf-8')
        
        async with aiohttp.ClientSession() as session:
            # Используем несколько провайдеров
            providers = [
                ('https://api.ocr.space/parse/image', {
                    'apikey': 'helloworld',
                    'language': 'rus',
                    'isOverlayRequired': 'false'
                }),
                ('https://ocr.sale/upload', {})  # Альтернативный
            ]
            
            for url, data in providers:
                data['base64Image'] = f'data:image/jpeg;base64,{image_base64}'
                try:
                    async with session.post(url, data=data, timeout=20) as resp:
                        if resp.status == 200:
                            result = await resp.json()
                            text = result.get('ParsedResults', [{}])[0].get('ParsedText', '')
                            if text.strip():
                                return text.strip()
                except:
                    continue
        
        return "Текст не обнаружен"
    except:
        return "Текст не обнаружен"

# ========== РАБОТА С ИСТОРИЕЙ (ОПТИМИЗИРОВАНО) ==========

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
    # Ограничиваем длину для экономии памяти
    if len(history) >= MAX_HISTORY_LENGTH * 2:
        history.pop(0)
    history.append({"role": role, "content": content[:1000]})  # Обрезаем историю
    save_chat_history()

def clear_history(user_id: int):
    user_id_str = str(user_id)
    chat_histories[user_id_str] = []
    save_chat_history()

def get_context_messages(user_id: int, max_messages: int = 6) -> list:
    """Берём меньше контекста для быстродействия"""
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
    
    if user_data["requests_today"] >= 50:  # Увеличил лимит до 50
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

# ========== ГИБРИДНЫЙ ЗАПРОС К GROQ (С АВТОВЫБОРОМ) ==========

async def hybrid_ask_groq(user_id: int, question: str, photo_text: Optional[str] = None) -> Tuple[str, str]:
    """
    Гибридный запрос с автоматическим выбором модели и умной обработкой
    """
    # Определяем тип задачи
    task_type = detect_task_type(question)
    
    # Выбираем модель
    if task_type['use_fast_model'] and len(question) < 200:
        model = user_models.get(user_id, FAST_MODEL)
    else:
        model = user_models.get(user_id, DEFAULT_MODEL)
    
    # Формируем полный запрос
    full_question = question
    if photo_text and photo_text != "Текст на фото не обнаружен" and not photo_text.startswith("Текст"):
        full_question = f"[Текст с фото: {photo_text[:500]}]\n\nВопрос пользователя: {question}"
    
    # Добавляем подсказку для математики
    if task_type['is_math']:
        full_question = f"🔢 МАТЕМАТИЧЕСКАЯ ЗАДАЧА\n{full_question}\n\nПожалуйста, реши подробно с объяснениями."
    
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    
    context = get_context_messages(user_id, max_messages=6)
    
    messages = [
        {"role": "system", "content": HYBRID_SYSTEM_PROMPT}
    ]
    
    for msg in context[-4:]:  # Берём только последние 4 сообщения для скорости
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
                    
                    # Обрезаем слишком длинные ответы
                    if len(answer) > 3500:
                        answer = answer[:3500] + "\n\n[Ответ сокращён из-за длины...]"
                    
                    return answer, model
                else:
                    return f"❌ Ошибка API: {resp.status}", model
        except asyncio.TimeoutError:
            return "⏰ Время ожидания истекло. Попробуй спросить короче.", model
        except Exception as e:
            return f"⚠️ Ошибка: {str(e)}", model

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
        [InlineKeyboardButton(text="📈 Запросы сегодня", callback_data="admin_requests")],
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
    
    welcome_msg = f"""🤖 *Гибридный AI-ассистент*

Привет! Я умею ВСЁ:

📚 *Отвечаю на любые вопросы*
🧮 *Решаю уравнения и примеры* (даже с фото!)
💻 *Помогаю с программированием*
📝 *Перевожу и анализирую текст*
✍️ *Пишу стихи и истории*

🎁 *Бесплатно:* {remaining}/50 запросов в день
📸 *Отправляй фото* — я распознаю текст, дроби и формулы!

Просто напиши вопрос или отправь фото 📸"""

    await message.answer(welcome_msg, reply_markup=get_main_keyboard(user_id), parse_mode="Markdown")
    await state.set_state(ChatState.waiting_for_question)

@dp.message(lambda message: message.text and message.text.startswith("📊 Статус"))
async def status_button(message: Message):
    user_id = message.from_user.id
    remaining = get_remaining_free_requests(user_id)
    user_data = get_user_data(user_id)
    total = user_data.get("total_requests", 0)
    
    model = user_models.get(user_id, DEFAULT_MODEL)
    model_name = MODELS.get(model, "Неизвестно")[:30]
    
    status_text = f"""📊 *Ваша статистика*

🎫 *Тариф:* Бесплатный
📝 *Осталось сегодня:* {remaining}/50
📈 *Всего запросов:* {total}

🧠 *Текущая модель:* {model_name}

✨ *Что умею:*
• 📸 Читаю текст с фото
• 🧮 Решаю математику
• 💻 Помогаю с кодом
• 📝 Перевод и анализ
• ✍️ Креативные задачи

💡 *Просто спроси что угодно!*"""

    await message.answer(status_text, parse_mode="Markdown", reply_markup=get_main_keyboard(user_id))

@dp.message(lambda message: message.text == "🧠 Выбрать модель")
async def change_model_button(message: Message):
    await message.answer(
        "🧠 *Выбери модель AI:*\n\n"
        "🦙 **Llama 70B** — мощная, для сложных задач (рекомендуется)\n"
        "⚡ **Llama 8B** — быстрая, для простых вопросов",
        reply_markup=model_choice_keyboard(),
        parse_mode="Markdown"
    )

@dp.message(lambda message: message.text == "❓ Помощь")
async def help_button(message: Message):
    help_text = """❓ *Как пользоваться ботом*

📝 *Простые вопросы:*
Просто напиши что хочешь узнать

📸 *Фото с задачами:*
1. Отправь фото
2. Добавь вопрос в подписи
3. Я распознаю текст и отвечу

🔢 *Математика:*
• x² - 5x + 6 = 0
• Найди производную x³+2x²
• Вычисли интеграл ∫3x²dx

💻 *Программирование:*
• Напиши функцию на Python
• Объясни алгоритм
• Найди ошибку в коде

📖 *Текст:*
• Переведи на английский
• Сделай краткий пересказ
• Напиши сочинение

🎁 *Бесплатно:* 50 запросов в день
🔄 *Сброс диалога:* кнопка "Сбросить диалог" """

    await message.answer(help_text, parse_mode="Markdown", reply_markup=get_main_keyboard(message.from_user.id))

@dp.message(lambda message: message.text == "ℹ️ О боте")
async def info_button(message: Message):
    info_text = """🤖 *Гибридный AI-ассистент*

Версия: 3.0 (Гибридная)

📌 *Технологии:*
• Groq API (мгновенные ответы)
• Llama 70B / 8B
• Tesseract OCR (распознавание фото)
• Память диалога

🎁 *Тариф:* Полностью бесплатный
• 50 запросов в день

🔧 *Функции:*
• Универсальные ответы
• Решение математики с фото
• Помощь в программировании
• Перевод и анализ текста
• Креативные задачи

👨‍💻 *Разработчик:* @SedoyDiada

⭐ *Бот полностью бесплатный!*"""

    await message.answer(info_text, parse_mode="Markdown", reply_markup=get_main_keyboard(message.from_user.id))

@dp.message(lambda message: message.text == "🔄 Сбросить диалог")
async def reset_button(message: Message, state: FSMContext):
    clear_history(message.from_user.id)
    await state.clear()
    await state.set_state(ChatState.waiting_for_question)
    await message.answer(
        "🔄 *Диалог сброшен!*\n\nИстория удалена, начинаем чистый разговор.",
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

# ========== ГЛАВНАЯ ОБРАБОТКА СООБЩЕНИЙ ==========

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
        # Пробуем распознать текст
        extracted_text = await extract_text_from_photo_advanced(photo.file_id)
        
        # Если не распозналось - пробуем API
        if extracted_text == "Текст на фото не обнаружен":
            extracted_text = await extract_text_alternative_api(photo.file_id)
        
        increment_request(user_id)
        
        # Получаем ответ от AI
        answer, used_model = await hybrid_ask_groq(user_id, user_question, extracted_text)
        
        # Сохраняем в историю
        add_to_history(user_id, "user", f"[Фото] {user_question}")
        add_to_history(user_id, "assistant", answer[:500])
        
        await thinking_msg.delete()
        
        # Показываем распознанный текст если есть
        if extracted_text and extracted_text != "Текст на фото не обнаружен" and len(extracted_text) < 500:
            await message.answer(f"📝 *Распознано:*\n```\n{extracted_text[:300]}\n```", parse_mode="Markdown")
        
        # Отправляем ответ с разбиением если длинный
        answer_parts = smart_split_text(answer)
        model_name = MODELS.get(used_model, "")
        
        for i, part in enumerate(answer_parts):
            footer = f"\n\n— {model_name}" if i == len(answer_parts)-1 and model_name else ""
            await message.answer(part + footer, parse_mode="Markdown", reply_markup=get_main_keyboard(user_id) if i == 0 else None)
        
        # Напоминание о лимите
        remaining = get_remaining_free_requests(user_id)
        if remaining <= 10:
            await message.answer(f"📊 *Осталось {remaining} запросов на сегодня*", parse_mode="Markdown")
                
    except Exception as e:
        await thinking_msg.delete()
        await message.answer(f"❌ Ошибка: {str(e)[:200]}\n\nПопробуй написать вопрос текстом.", reply_markup=get_main_keyboard(user_id))

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
    
    # Проверка длины
    if len(question) > 3000:
        await message.answer("⚠️ *Слишком длинный запрос* (макс 3000 символов)\n\nПожалуйста, сократи вопрос.", parse_mode="Markdown")
        return
    
    can_request, error_msg = can_make_request(user_id)
    if not can_request:
        await message.answer(error_msg, parse_mode="Markdown", reply_markup=get_main_keyboard(user_id))
        return
    
    increment_request(user_id)
    
    await bot.send_chat_action(message.chat.id, "typing")
    thinking_msg = await message.answer("🤔 *Думаю...*", parse_mode="Markdown")
    
    try:
        # Получаем ответ
        answer, used_model = await hybrid_ask_groq(user_id, question)
        
        # Сохраняем в историю
        add_to_history(user_id, "user", question[:500])
        add_to_history(user_id, "assistant", answer[:500])
        
        await thinking_msg.delete()
        
        # Разбиваем длинный ответ
        answer_parts = smart_split_text(answer)
        model_name = MODELS.get(used_model, "")
        
        for i, part in enumerate(answer_parts):
            footer = f"\n\n— {model_name}" if i == len(answer_parts)-1 and model_name else ""
            await message.answer(part + footer, parse_mode="Markdown", reply_markup=get_main_keyboard(user_id) if i == 0 else None)
        
        # Напоминание о лимите
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

📅 *Дата:* {datetime.now().strftime('%d.%m.%Y %H:%M')}

✅ *Всё работает бесплатно!*"""
    
    await callback.message.edit_text(stats_text, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(lambda c: c.data == "admin_requests")
async def admin_requests(callback: CallbackQuery):
    if not is_owner(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён")
        return
    
    users_data = load_users_data()
    today = datetime.now().strftime("%Y-%m-%d")
    
    top_users = []
    for uid, data in users_data.items():
        if data.get("last_reset") == today:
            requests = data.get("requests_today", 0)
            if requests > 0:
                top_users.append((uid, requests, data.get("username", "unknown")))
    
    top_users.sort(key=lambda x: x[1], reverse=True)
    top_10 = top_users[:10]
    
    text = "📊 *Топ пользователей сегодня*\n\n"
    for i, (uid, req, name) in enumerate(top_10, 1):
        text += f"{i}. @{name}: {req} запросов\n"
    
    await callback.message.edit_text(text, parse_mode="Markdown")
    await callback.answer()

@dp.message(Command("cancel"))
async def cancel_handler(message: Message, state: FSMContext):
    await state.set_state(ChatState.waiting_for_question)
    await message.answer("❌ Отменено", reply_markup=get_main_keyboard(message.from_user.id))

# ========== ЗАПУСК ==========

async def main():
    print("=" * 60)
    print("🤖 ГИБРИДНЫЙ AI-АССИСТЕНТ ЗАПУЩЕН")
    print("=" * 60)
    print(f"👑 Владелец: {OWNER_ID}")
    print(f"🤖 Модели: Llama 70B, Llama 8B")
    print(f"📸 OCR: Tesseract (продвинутый)")
    print(f"🎁 Лимит: 50 запросов/день")
    print(f"✨ Функции: Универсальные ответы + Математика + Код + Текст")
    print("=" * 60)
    
    # Создаём файлы
    for file in [DATA_FILE, HISTORY_FILE]:
        if not os.path.exists(file):
            with open(file, 'w', encoding='utf-8') as f:
                json.dump({}, f)
            print(f"📁 Создан {file}")
    
    # Загружаем историю
    history_data = load_chat_history()
    for user_id, history in history_data.items():
        chat_histories[user_id] = history
    print(f"📁 Загружена история для {len(chat_histories)} пользователей")
    
    # Проверяем Tesseract
    try:
        result = subprocess.run(['tesseract', '--version'], capture_output=True, text=True)
        if result.returncode == 0:
            print("✅ Tesseract OCR установлен (поддержка дробей и формул)")
        else:
            print("⚠️ Tesseract не найден. OCR будет работать через API")
    except:
        print("⚠️ Tesseract не найден. Установите: sudo apt-get install tesseract-ocr tesseract-ocr-rus")
    
    print("=" * 60)
    print("✅ БОТ ГОТОВ К РАБОТЕ!")
    print("📌 Что умеет:")
    print("   • 📸 Распознавать текст с фото (включая дроби)")
    print("   • 🧮 Решать уравнения и примеры")
    print("   • 💻 Помогать с программированием")
    print("   • 📝 Переводить и анализировать текст")
    print("   • ✍️ Писать креативные тексты")
    print("=" * 60)
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())