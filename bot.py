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
from collections import defaultdict
import base64
import subprocess
import tempfile

# ========== КОНФИГУРАЦИЯ ==========

GROQ_API_KEY = "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"
OWNER_ID = 5439940299

DATA_FILE = "users_data.json"
HISTORY_FILE = "chat_history.json"
MAX_HISTORY_LENGTH = 20

# Только бесплатные модели Groq
FREE_MODELS = {
    "llama-3.3-70b-versatile": "🦙 Llama 70B",
    "llama-3.1-8b-instant": "⚡ Llama 8B"
}

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

bot = Bot(
    token="8857441987:AAH18rhUKO8MvxzJvm0TPlCaxksHrlHycww",
    default=DefaultBotProperties(parse_mode="Markdown")
)

dp = Dispatcher(storage=MemoryStorage())
user_models = {}
chat_histories = defaultdict(list)

# ========== OCR ЧЕРЕЗ TESSERACT (ЛОКАЛЬНО, БЕСПЛАТНО) ==========

async def extract_text_from_photo(photo_file_id: str) -> str:
    """
    Извлекает текст из фото через Tesseract OCR (полностью бесплатно)
    """
    try:
        # Скачиваем фото
        file = await bot.get_file(photo_file_id)
        file_bytes = await bot.download_file(file.file_path)
        
        # Сохраняем временный файл
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp_file:
            tmp_file.write(file_bytes.getvalue())
            tmp_path = tmp_file.name
        
        # Используем Tesseract для распознавания текста
        # Для установки: sudo apt-get install tesseract-ocr tesseract-ocr-rus
        result = subprocess.run(
            ['tesseract', tmp_path, 'stdout', '-l', 'rus+eng', '--psm', '6'],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        # Удаляем временный файл
        os.unlink(tmp_path)
        
        if result.returncode == 0:
            extracted_text = result.stdout.strip()
            if extracted_text:
                return extracted_text
            else:
                return "Текст на фото не обнаружен"
        else:
            return f"[Ошибка Tesseract: {result.stderr}]"
            
    except subprocess.TimeoutExpired:
        return "[Таймаут при распознавании]"
    except FileNotFoundError:
        return "[Tesseract не установлен. Установите: sudo apt-get install tesseract-ocr tesseract-ocr-rus]"
    except Exception as e:
        print(f"❌ Ошибка OCR: {e}")
        return f"[Ошибка обработки фото: {str(e)}]"

# ========== АЛЬТЕРНАТИВНЫЙ OCR ЧЕРЕЗ API (ЗАПАСНОЙ ВАРИАНТ) ==========

async def extract_text_alternative(photo_file_id: str) -> str:
    """
    Запасной вариант OCR через бесплатный API
    """
    try:
        file = await bot.get_file(photo_file_id)
        file_bytes = await bot.download_file(file.file_path)
        image_base64 = base64.b64encode(file_bytes.getvalue()).decode('utf-8')
        
        # Бесплатный OCR API
        async with aiohttp.ClientSession() as session:
            data = {
                'base64Image': f'data:image/jpeg;base64,{image_base64}',
                'apikey': 'helloworld',
                'language': 'rus',
                'isOverlayRequired': 'false'
            }
            
            async with session.post('https://api.ocr.space/parse/image', data=data, timeout=30) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    if not result.get('IsErroredOnProcessing'):
                        parsed_text = result.get('ParsedResults', [{}])[0].get('ParsedText', '')
                        if parsed_text.strip():
                            return parsed_text.strip()
        return "Текст не обнаружен"
    except:
        return "Текст не обнаружен"

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
    history.append({"role": role, "content": content})
    if len(history) > MAX_HISTORY_LENGTH:
        history.pop(0)
    save_chat_history()

def clear_history(user_id: int):
    user_id_str = str(user_id)
    chat_histories[user_id_str] = []
    save_chat_history()

def get_context_messages(user_id: int, max_messages: int = 10) -> list:
    history = get_user_history(user_id)
    recent = history[-max_messages:] if len(history) > max_messages else history
    return recent

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
    
    # Бесплатный лимит - 20 запросов в день (увеличил с 5)
    if user_data["requests_today"] >= 20:
        return False, "⏰ *Лимит 20 бесплатных запросов в день исчерпан!*\n\nВозвращайся завтра или поддержи проект донатом."
    
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
    return max(0, 20 - user_data["requests_today"])

def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID

# ========== ЗАПРОС К GROQ ==========

async def ask_groq_with_memory(user_id: int, question: str, model: str) -> str:
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    
    context = get_context_messages(user_id, max_messages=10)
    
    messages = []
    messages.append({
        "role": "system",
        "content": "Ты полезный AI-ассистент. Отвечай на русском языке, дружелюбно и информативно."
    })
    
    for msg in context:
        messages.append(msg)
    
    messages.append({"role": "user", "content": question})
    
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 800
    }
    
    timeout = aiohttp.ClientTimeout(total=60)
    
    async with aiohttp.ClientSession(timeout=timeout) as session:
        try:
            async with session.post(GROQ_API_URL, headers=headers, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data["choices"][0]["message"]["content"]
                else:
                    return f"❌ Ошибка API: {resp.status}"
        except asyncio.TimeoutError:
            return "⏰ Превышено время ожидания."
        except Exception as e:
            return f"⚠️ Ошибка: {str(e)}"

# ========== КЛАВИАТУРЫ ==========

def get_main_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    remaining = get_remaining_free_requests(user_id)
    
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=f"📊 Статус | 🎫 Осталось: {remaining}/20")],
            [KeyboardButton(text="🧠 Сменить модель")],
            [KeyboardButton(text="ℹ️ О боте"), KeyboardButton(text="🔄 Сбросить диалог")]
        ],
        resize_keyboard=True
    )
    return keyboard

def model_choice_keyboard():
    buttons = []
    for model_id, model_name in FREE_MODELS.items():
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
    user_models[message.from_user.id] = "llama-3.3-70b-versatile"
    
    username = message.from_user.username
    if username:
        update_user_data(message.from_user.id, {"username": username})
    
    remaining = get_remaining_free_requests(message.from_user.id)
    
    welcome_msg = f"""🌟 *Добро пожаловать в бесплатного AI-ассистента!*

🎁 *Что ты получаешь бесплатно:*
• 📸 Распознавание текста с фото (OCR)
• 🧠 Память диалога (помню контекст)
• 🤖 Доступ к Llama 70B и Llama 8B
• 📝 20 запросов в день

📸 *Как пользоваться:*
• Просто напиши вопрос
• Отправь фото с вопросом в подписи
• Используй кнопки в меню

💡 *Совет:* Чем подробнее вопрос, тем лучше ответ!

🎉 *Приятного общения!*"""

    await message.answer(welcome_msg, reply_markup=get_main_keyboard(message.from_user.id), parse_mode="Markdown")
    await state.set_state(ChatState.waiting_for_question)

@dp.message(lambda message: message.text and message.text.startswith("📊 Статус"))
async def status_button(message: Message):
    user_id = message.from_user.id
    remaining = get_remaining_free_requests(user_id)
    user_data = get_user_data(user_id)
    total = user_data.get("total_requests", 0)
    
    status_text = f"""📊 *Ваша статистика*

🎫 *Бесплатный тариф*
• Доступно сегодня: {remaining}/20 запросов
• Всего использовано: {total} запросов

✨ *Функции:*
✅ Распознавание текста с фото
✅ Память диалога
✅ Бесплатные модели AI

💡 *Поддержать проект:* @SedoyDiada"""

    await message.answer(status_text, parse_mode="Markdown", reply_markup=get_main_keyboard(user_id))

@dp.message(lambda message: message.text == "🧠 Сменить модель")
async def change_model_button(message: Message):
    await message.answer("🧠 *Выбери модель AI:*\n\n🦙 Llama 70B - мощная, для сложных задач\n⚡ Llama 8B - быстрая, для простых вопросов", 
                        reply_markup=model_choice_keyboard(), parse_mode="Markdown")

@dp.message(lambda message: message.text == "ℹ️ О боте")
async def info_button(message: Message):
    info_text = """🤖 *О боте*

📌 *Возможности:*
• 📸 Распознавание текста с фото
• 🧠 Контекстная память
• 🔄 Смена моделей AI
• 📊 Статистика использования

🎁 *Тариф:* Полностью бесплатно
• 20 запросов в день

🔧 *Технологии:*
• Groq API (Llama 70B/8B)
• Tesseract OCR
• Aiogram 3.x

👨‍💻 *Разработчик:* @SedoyDiada
⭐ *Поддержи проект звездой на GitHub!*"""

    await message.answer(info_text, parse_mode="Markdown", reply_markup=get_main_keyboard(message.from_user.id))

@dp.message(lambda message: message.text == "🔄 Сбросить диалог")
async def reset_button(message: Message, state: FSMContext):
    clear_history(message.from_user.id)
    await state.clear()
    await state.set_state(ChatState.waiting_for_question)
    await message.answer("🔄 *Диалог сброшен!*\n\nИстория удалена, начинаем чистый разговор.", 
                        parse_mode="Markdown", reply_markup=get_main_keyboard(message.from_user.id))

@dp.callback_query(lambda c: c.data.startswith("model_"))
async def process_model_choice(callback: CallbackQuery):
    model_id = callback.data.replace("model_", "")
    user_models[callback.from_user.id] = model_id
    model_name = FREE_MODELS.get(model_id, "Неизвестно")
    
    await callback.message.edit_text(f"✅ *Модель изменена на {model_name}*", parse_mode="Markdown")
    await callback.message.answer("✨ Готов к работе!", reply_markup=get_main_keyboard(callback.from_user.id))
    await callback.answer()

@dp.callback_query(lambda c: c.data == "close")
async def close_callback(callback: CallbackQuery):
    await callback.message.delete()
    await callback.answer()

# ========== ОБРАБОТКА ФОТО ==========

@dp.message(ChatState.waiting_for_question, lambda message: message.photo)
async def handle_photo(message: Message):
    user_id = message.from_user.id
    
    can_request, error_msg = can_make_request(user_id)
    if not can_request:
        await message.answer(error_msg, parse_mode="Markdown", reply_markup=get_main_keyboard(user_id))
        return
    
    photo = message.photo[-1]
    
    await bot.send_chat_action(message.chat.id, "typing")
    thinking_msg = await message.answer("📸 *Анализирую фото...*", parse_mode="Markdown")
    
    try:
        # Пробуем локальный Tesseract
        extracted_text = await extract_text_from_photo(photo.file_id)
        
        # Если Tesseract не сработал, пробуем API
        if extracted_text.startswith("[Ошибка") or extracted_text.startswith("[Tesseract"):
            extracted_text = await extract_text_alternative(photo.file_id)
        
        user_question = message.caption or "Что написано на этом изображении?"
        
        increment_request(user_id)
        
        model = user_models.get(user_id, "llama-3.3-70b-versatile")
        model_name = FREE_MODELS.get(model, "")
        
        if extracted_text and "не обнаружен" not in extracted_text and not extracted_text.startswith("["):
            full_prompt = f"""Пользователь отправил фото. Распознанный текст с фото:
{extracted_text}

Вопрос пользователя: {user_question}

Ответь на вопрос, используя информацию с фото. Если вопрос обобщающий, ответь основываясь на тексте."""
            
            # Показываем распознанный текст
            preview = extracted_text[:400] + "..." if len(extracted_text) > 400 else extracted_text
            await message.answer(f"📝 *Распознанный текст:*\n```\n{preview}\n```", parse_mode="Markdown")
        else:
            full_prompt = user_question
        
        answer = await ask_groq_with_memory(user_id, full_prompt, model)
        
        add_to_history(user_id, "user", f"[Фото] {user_question}")
        add_to_history(user_id, "assistant", answer)
        
        await thinking_msg.delete()
        
        response = f"{answer}\n\n— {model_name}" if model_name else answer
        await message.answer(response, parse_mode="Markdown", reply_markup=get_main_keyboard(user_id))
        
        remaining = get_remaining_free_requests(user_id)
        if remaining <= 5:
            await message.answer(f"📊 *Осталось {remaining} запросов на сегодня*\nВозвращайся завтра!", 
                                parse_mode="Markdown", reply_markup=get_main_keyboard(user_id))
                
    except Exception as e:
        await thinking_msg.delete()
        await message.answer(f"❌ Ошибка: {str(e)}\n\nПопробуй отправить фото в лучшем качестве или просто напиши вопрос текстом.", 
                            reply_markup=get_main_keyboard(user_id))

# ========== ОБРАБОТКА ТЕКСТОВЫХ ВОПРОСОВ ==========

@dp.message(ChatState.waiting_for_question)
async def handle_question(message: Message):
    question = message.text.strip()
    
    # Игнорируем кнопки
    buttons = ["📊 Статус", "🧠 Сменить модель", "ℹ️ О боте", "🔄 Сбросить диалог"]
    if any(question == btn or question.startswith("📊 Статус") for btn in buttons):
        return
    
    if not question:
        return
    
    user_id = message.from_user.id
    
    can_request, error_msg = can_make_request(user_id)
    if not can_request:
        await message.answer(error_msg, parse_mode="Markdown", reply_markup=get_main_keyboard(user_id))
        return
    
    if len(question) > 2000:
        await message.answer("⚠️ *Слишком длинный запрос* (макс 2000 символов)\n\nСократи вопрос и попробуй снова.", parse_mode="Markdown")
        return
    
    increment_request(user_id)
    
    await bot.send_chat_action(message.chat.id, "typing")
    thinking_msg = await message.answer("🤔 *Думаю...*", parse_mode="Markdown")
    
    model = user_models.get(user_id, "llama-3.3-70b-versatile")
    model_name = FREE_MODELS.get(model, "")
    
    answer = await ask_groq_with_memory(user_id, question, model)
    
    add_to_history(user_id, "user", question)
    add_to_history(user_id, "assistant", answer)
    
    await thinking_msg.delete()
    
    response = f"{answer}\n\n— {model_name}" if model_name else answer
    await message.answer(response, parse_mode="Markdown", reply_markup=get_main_keyboard(user_id))
    
    remaining = get_remaining_free_requests(user_id)
    if remaining <= 5:
        await message.answer(f"📊 *Осталось {remaining} запросов на сегодня*", parse_mode="Markdown", reply_markup=get_main_keyboard(user_id))

# ========== АДМИН ==========

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

👥 *Пользователи:* {total_users}
📝 *Запросов сегодня:* {total_requests_today}
📈 *Всего запросов:* {total_requests_all}
🧠 *Активных диалогов:* {len(chat_histories)}

📅 *Дата:* {datetime.now().strftime('%d.%m.%Y %H:%M')}

⚙️ *Всё работает бесплатно!*"""
    
    await callback.message.edit_text(stats_text, parse_mode="Markdown")
    await callback.answer()

# ========== ЗАПУСК ==========

async def main():
    print("=" * 50)
    print("🚀 БОТ ЗАПУЩЕН (ПОЛНОСТЬЮ БЕСПЛАТНАЯ ВЕРСИЯ)")
    print("=" * 50)
    print(f"👑 Владелец: {OWNER_ID}")
    print(f"🤖 Модели: Llama 70B, Llama 8B")
    print(f"📸 OCR: Tesseract (локальный) + API (резервный)")
    print(f"🎁 Лимит: 20 запросов/день")
    print("=" * 50)
    
    # Создаём файлы если их нет
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump({}, f)
        print("📁 Создан users_data.json")
    
    if not os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump({}, f)
        print("📁 Создан chat_history.json")
    
    # Загружаем историю
    history_data = load_chat_history()
    for user_id, history in history_data.items():
        chat_histories[user_id] = history
    print(f"📁 Загружена история для {len(chat_histories)} пользователей")
    
    # Проверяем Tesseract
    try:
        result = subprocess.run(['tesseract', '--version'], capture_output=True, text=True)
        if result.returncode == 0:
            print("✅ Tesseract OCR установлен")
        else:
            print("⚠️ Tesseract не найден. Установите: sudo apt-get install tesseract-ocr tesseract-ocr-rus")
    except:
        print("⚠️ Tesseract не найден. OCR будет работать через API (может быть медленнее)")
    
    print("=" * 50)
    print("✅ БОТ ГОТОВ К РАБОТЕ!")
    print("=" * 50)
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())