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

# ========== ДОПОЛНИТЕЛЬНЫЕ ИМПОРТЫ ==========
import base64

# ========== КОНФИГУРАЦИЯ ==========

GROQ_API_KEY = "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"

# ========== ВЛАДЕЛЕЦ БОТА (ID из Telegram) ==========
OWNER_ID = 5439940299

# Цена подписки в звёздах
STAR_PRICE = 30

# Файл для хранения данных пользователей
DATA_FILE = "users_data.json"

# Файл для хранения истории диалогов
HISTORY_FILE = "chat_history.json"

# Максимальное количество сообщений в истории (на пользователя)
MAX_HISTORY_LENGTH = 20

# Модели
FREE_MODELS = {
    "llama-3.3-70b-versatile": "🦙 Llama 70B",
    "llama-3.1-8b-instant": "⚡ Llama 8B",
    "llama-3.2-90b-vision-preview": "👁️ Llama 90B Vision"
}

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

# Инициализация бота
bot = Bot(
    token="8666211095:AAGk41YRGTBIaezj5MzKQ1eFTIMVV8YIiqM",
    default=DefaultBotProperties(parse_mode="Markdown")
)

dp = Dispatcher(storage=MemoryStorage())
user_models = {}

# Хранилище истории диалогов
chat_histories = defaultdict(list)

# ========== РАБОТА С ИСТОРИЕЙ ДИАЛОГОВ ==========

def load_chat_history():
    """Загружает историю диалогов из файла"""
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_chat_history():
    """Сохраняет историю диалогов в файл"""
    history_dict = dict(chat_histories)
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(history_dict, f, ensure_ascii=False, indent=2)

def get_user_history(user_id: int) -> list:
    """Получает историю диалога пользователя"""
    user_id_str = str(user_id)
    if user_id_str not in chat_histories:
        chat_histories[user_id_str] = []
    return chat_histories[user_id_str]

def add_to_history(user_id: int, role: str, content: str):
    """Добавляет сообщение в историю"""
    user_id_str = str(user_id)
    history = get_user_history(user_id)
    history.append({"role": role, "content": content})
    
    # Ограничиваем длину истории
    if len(history) > MAX_HISTORY_LENGTH:
        history.pop(0)
    
    # Сохраняем в файл
    save_chat_history()

def clear_history(user_id: int):
    """Очищает историю диалога пользователя"""
    user_id_str = str(user_id)
    chat_histories[user_id_str] = []
    save_chat_history()

def get_context_messages(user_id: int, max_messages: int = 10) -> list:
    """Возвращает последние N сообщений для контекста"""
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
    return user_id == OWNER_ID

# ========== РАСПОЗНАВАНИЕ ТЕКСТА С ФОТО ==========

async def extract_text_from_photo(photo_file_id: str) -> str:
    """
    Извлекает текст из фото используя Groq Vision API
    """
    try:
        # Скачиваем фото
        file = await bot.get_file(photo_file_id)
        file_bytes = await bot.download_file(file.file_path)
        
        # Конвертируем в base64
        image_data = base64.b64encode(file_bytes.getvalue()).decode('utf-8')
        
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "llama-3.2-90b-vision-preview",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Извлеки весь текст с этого изображения. Если текста нет, напиши 'Текст не обнаружен'. Если видишь код или цифры, тоже извлеки их точно. Отвечай только извлечённым текстом, без лишних комментариев."
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_data}"
                            }
                        }
                    ]
                }
            ],
            "temperature": 0.1,
            "max_tokens": 1000
        }
        
        timeout = aiohttp.ClientTimeout(total=30)
        
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(GROQ_API_URL, headers=headers, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    extracted_text = data["choices"][0]["message"]["content"]
                    return extracted_text
                else:
                    return f"[Ошибка OCR: {resp.status}]"
    except Exception as e:
        return f"[Ошибка обработки фото: {str(e)}]"

# ========== ЗАПРОС К GROQ С ПАМЯТЬЮ ==========

async def ask_groq_with_memory(user_id: int, question: str, model: str, photo_text: str = None) -> str:
    """
    Отправляет запрос к Groq с учётом истории диалога
    """
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    
    # Формируем полный запрос с учётом текста с фото
    full_question = question
    if photo_text and photo_text != "[Текст не обнаружен]":
        full_question = f"Вот текст с фото: {photo_text}\n\nВопрос пользователя: {question}"
    
    # Получаем историю диалога
    context = get_context_messages(user_id, max_messages=10)
    
    # Строим сообщения для API
    messages = []
    
    # Добавляем системный промпт
    messages.append({
        "role": "system",
        "content": "Ты полезный AI-ассистент. У тебя есть память о предыдущих сообщениях в этом диалоге. Отвечай последовательно, учитывая контекст разговора. Если пользователь отправил фото с текстом, используй его в ответе."
    })
    
    # Добавляем историю
    for msg in context:
        messages.append(msg)
    
    # Добавляем текущий запрос
    messages.append({"role": "user", "content": full_question})
    
    if len(full_question) > 3000:
        full_question = full_question[:3000] + "\n\n[сообщение обрезано]"
    
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 800
    }
    
    timeout = aiohttp.ClientTimeout(total=60, connect=10, sock_read=30)
    
    async with aiohttp.ClientSession(timeout=timeout) as session:
        try:
            async with session.post(GROQ_API_URL, headers=headers, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    answer = data["choices"][0]["message"]["content"]
                    if len(answer) > 3500:
                        answer = answer[:3500] + "\n\n[Ответ обрезан]"
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
        welcome_msg = f"🌟 *Добро пожаловать!*\n\nУ тебя активна подписка до `{sub_until}`\n\n📸 Могу читать текст с фото!\n🧠 Помню предыдущие сообщения!\n\nПросто напиши вопрос или отправь фото."
    else:
        welcome_msg = f"🌟 *Добро пожаловать!*\n\nУ тебя {remaining}/5 бесплатных запросов в день.\n\n📸 Могу читать текст с фото!\n🧠 Помню предыдущие сообщения!\n\n💎 Оформи подписку за {STAR_PRICE} звёзд в месяц для неограниченного доступа.\n\nПросто напиши вопрос или отправь фото."
    
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
        status_text = f"💎 *Премиум подписка*\nАктивна до: `{sub_until}`\n\n✅ Неограниченные запросы\n✅ Память диалога\n✅ Чтение текста с фото"
    else:
        status_text = f"🎫 *Бесплатный тариф*\nОсталось запросов сегодня: {remaining}/5\n\n✅ Память диалога\n✅ Чтение текста с фото\n\n💎 Купи подписку за {STAR_PRICE} звёзд"
    
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
        f"✅ Безлимитные запросы\n"
        f"✅ Память диалога\n"
        f"✅ Чтение текста с фото\n\n"
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
        "🧠 *Выбери модель:*\n\n"
        "👁️ Llama 90B Vision - умеет читать текст с фото",
        reply_markup=model_choice_keyboard(),
        parse_mode="Markdown"
    )

@dp.message(lambda message: message.text == "ℹ️ О боте")
async def info_button(message: Message):
    await message.answer(
        "🤖 *О боте*\n\n"
        "📌 *Функции:*\n"
        "• 📸 Распознавание текста с фото (OCR)\n"
        "• 🧠 Память диалога (помнит предыдущие сообщения)\n"
        "• 🤖 Несколько моделей ИИ\n"
        "• 💰 Подписка для безлимита\n\n"
        f"💰 *Тарифы:*\n"
        f"• Бесплатно: 5 запросов/день\n"
        f"• Премиум: {STAR_PRICE} звёзд/месяц\n\n"
        f"👤 Владелец: @SedoyDiada",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(message.from_user.id)
    )

@dp.message(lambda message: message.text == "🔄 Сбросить диалог")
async def reset_button(message: Message, state: FSMContext):
    clear_history(message.from_user.id)
    await state.clear()
    await state.set_state(ChatState.waiting_for_question)
    await message.answer(
        "🔄 *Диалог сброшен!*\n\nИстория предыдущих сообщений удалена.",
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

# ========== ОБРАБОТКА ФОТО И ВОПРОСОВ ==========

@dp.message(ChatState.waiting_for_question, lambda message: message.photo)
async def handle_photo(message: Message, state: FSMContext):
    """Обработка фото с вопросом"""
    user_id = message.from_user.id
    
    # Проверяем лимиты
    can_request, error_msg = can_make_request(user_id)
    if not can_request:
        await message.answer(
            error_msg,
            parse_mode="Markdown",
            reply_markup=get_main_keyboard(user_id)
        )
        return
    
    # Получаем лучшее качество фото
    photo = message.photo[-1]
    
    await bot.send_chat_action(message.chat.id, "typing")
    
    thinking_msg = await message.answer("📸 *Обрабатываю фото и думаю...*", parse_mode="Markdown")
    
    try:
        # Извлекаем текст с фото
        extracted_text = await extract_text_from_photo(photo.file_id)
        
        # Вопрос пользователя (если есть)
        user_question = message.caption or "Что написано на этом изображении?"
        
        # Увеличиваем счётчик запросов (если нет подписки)
        if not has_active_subscription(user_id):
            increment_request(user_id)
        
        model = user_models.get(user_id, "llama-3.2-90b-vision-preview")
        model_name = FREE_MODELS.get(model, "Неизвестно")
        
        # Формируем запрос с извлечённым текстом
        full_prompt = f"На фото был извлечён следующий текст:\n{extracted_text}\n\nВопрос пользователя: {user_question}"
        
        # Отправляем запрос с учётом истории
        answer = await ask_groq_with_memory(user_id, full_prompt, model)
        
        # Сохраняем в историю
        add_to_history(user_id, "user", f"[Фото] {user_question}")
        add_to_history(user_id, "assistant", answer)
        
        await thinking_msg.delete()
        
        # Отправляем ответ
        response_text = f"{answer}\n\n— {model_name}"
        if "[Ошибка" in extracted_text:
            response_text = f"⚠️ {extracted_text}\n\n{answer}\n\n— {model_name}"
        
        await message.answer(
            response_text,
            parse_mode="Markdown",
            reply_markup=get_main_keyboard(user_id)
        )
        
        # Напоминание о лимите
        if not has_active_subscription(user_id):
            remaining = get_remaining_free_requests(user_id)
            if remaining <= 2 and remaining > 0:
                await message.answer(
                    f"⚠️ Осталось {remaining} бесплатных запросов на сегодня.\n"
                    f"Купи подписку за {STAR_PRICE} звёзд — @SedoyDiada",
                    parse_mode="Markdown"
                )
                
    except Exception as e:
        await thinking_msg.delete()
        await message.answer(
            f"❌ Ошибка при обработке фото: {str(e)}",
            reply_markup=get_main_keyboard(user_id)
        )

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
    
    # Проверка лимитов
    can_request, error_msg = can_make_request(message.from_user.id)
    if not can_request:
        await message.answer(
            error_msg,
            parse_mode="Markdown",
            reply_markup=get_main_keyboard(message.from_user.id)
        )
        return
    
    if len(question) > 2000:
        await message.answer(
            f"⚠️ *Слишком длинный запрос* ({len(question)} символов)\n\nСократи до 2000 символов.",
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
        # Отправляем запрос с учётом истории
        answer = await ask_groq_with_memory(message.from_user.id, question, model)
        
        # Сохраняем в историю
        add_to_history(message.from_user.id, "user", question)
        add_to_history(message.from_user.id, "assistant", answer)
        
    except asyncio.TimeoutError:
        answer = "⏰ Превышено время ожидания. Попробуй ещё раз."
    
    await thinking_msg.delete()
    
    await message.answer(
        f"{answer}\n\n— {model_name}",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(message.from_user.id)
    )
    
    # Напоминание о лимите
    if not has_active_subscription(message.from_user.id):
        remaining = get_remaining_free_requests(message.from_user.id)
        if remaining <= 2 and remaining > 0:
            await message.answer(
                f"⚠️ У вас осталось {remaining} бесплатных запросов на сегодня.\n"
                f"Купи подписку за {STAR_PRICE} звёзд для безлимита — @SedoyDiada",
                parse_mode="Markdown"
            )

# ========== АДМИН-КОМАНДЫ ==========

@dp.message(Command("admin"))
async def admin_panel(message: Message):
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
    if not is_owner(message.from_user.id):
        await message.answer("⛔ Доступ запрещён")
        await state.clear()
        return
    
    user_input = message.text.strip()
    
    target_user_id = None
    target_username = None
    
    if user_input.isdigit():
        target_user_id = int(user_input)
    else:
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
    
    try:
        await bot.send_message(
            target_user_id,
            f"🎉 *Поздравляем!*\n\n"
            f"Вам выдана премиум подписка до `{expiry_date}`\n\n"
            f"Теперь у вас неограниченное количество запросов!\n"
            f"📸 Отправляйте фото - я прочитаю текст!\n"
            f"🧠 Я помню всю историю диалога!",
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
    total_history = sum(len(hist) for hist in chat_histories.values())
    
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
        f"🧠 Всего сообщений в истории: {total_history}\n"
        f"📅 Данные на: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
    )
    
    await callback.message.edit_text(stats_text, parse_mode="Markdown")
    await callback.answer()

@dp.message(Command("cancel"))
async def cancel_admin(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        await message.answer("⛔ Доступ запрещён")
        return
    await state.clear()
    await message.answer("❌ Действие отменено")

# ========== ЗАПУСК ==========

async def main():
    print("🚀 Бот с платной подпиской запущен...")
    print("👁️ Добавлены функции:")
    print("   📸 Распознавание текста с фото (OCR)")
    print("   🧠 Память диалога (контекст)")
    print(f"👑 ID владельца: {OWNER_ID}")
    print(f"💰 Цена подписки: {STAR_PRICE} звёзд/месяц")
    print("✅ Готов к работе!")
    
    if OWNER_ID == 123456789:
        print("⚠️ ВНИМАНИЕ! Ты не поменял OWNER_ID на свой!")
    
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump({}, f)
        print("📁 Создан файл users_data.json")
    
    # Загружаем историю
    history_data = load_chat_history()
    for user_id, history in history_data.items():
        chat_histories[user_id] = history
    print(f"📁 Загружена история для {len(chat_histories)} пользователей")
    
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