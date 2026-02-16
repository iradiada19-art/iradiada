#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# bot.py - С ЗАМЕТКАМИ И ЧАТОМ

import json
import os
import asyncio
import logging
import requests
import re
from datetime import datetime, timedelta
from groq import Groq
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from pytz import timezone
import pytz

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# ================== НАСТРОЙКА ЛОГИРОВАНИЯ ==================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ================== ПРОВЕРКА ПЕРЕМЕННЫХ ОКРУЖЕНИЯ ==================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GROQ_API_KEY = "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"

if not TELEGRAM_BOT_TOKEN:
    logger.error("❌ TELEGRAM_BOT_TOKEN не найден!")
    raise RuntimeError("TELEGRAM_BOT_TOKEN обязательно должен быть задан")

logger.info("✅ Токены успешно загружены")

# ================== ЧАСОВОЙ ПОЯС ==================
MSK_TZ = timezone('Europe/Moscow')
logger.info(f"🕐 Часовой пояс: {MSK_TZ}")

# ================== ФАЙЛЫ ДЛЯ СОХРАНЕНИЯ ==================
REMINDERS_FILE = "/tmp/reminders.json"
NOTES_FILE = "/tmp/notes.json"
logger.info(f"📁 Файл напоминаний: {REMINDERS_FILE}")
logger.info(f"📁 Файл заметок: {NOTES_FILE}")

# ================== КОНСТАНТЫ ==================
BTN_START = "Узнать погоду"
BTN_UPDATE = "Обновить прогноз"
BTN_REMINDERS = "Напоминания"
BTN_NOTES = "Мои заметки"
BTN_CHAT = "Поболтать"

# Главная клавиатура
main_keyboard = ReplyKeyboardMarkup(
    [[BTN_START, BTN_UPDATE], [BTN_REMINDERS, BTN_NOTES], [BTN_CHAT]],
    resize_keyboard=True,
)

# Клавиатура меню напоминаний
reminders_keyboard = ReplyKeyboardMarkup(
    [["📝 Создать", "📋 Список"], ["❌ Удалить", "🔙 Назад"]],
    resize_keyboard=True
)

# Клавиатура меню заметок
notes_keyboard = ReplyKeyboardMarkup(
    [["📝 Новая заметка", "📋 Все заметки"], ["❌ Удалить заметку", "🔙 Назад"]],
    resize_keyboard=True
)

# Инициализация Groq клиента
try:
    groq_client = Groq(api_key=GROQ_API_KEY)
    logger.info("✅ Groq клиент инициализирован")
except Exception as e:
    logger.error(f"❌ Ошибка инициализации Groq: {e}")
    groq_client = None

# Хранилища данных
user_cities = {}  # {user_id: city_name}
user_reminders = {}  # {user_id: [{"id": 1, "text": "...", "time": "...", "job_id": "..."}]}
user_notes = {}  # {user_id: [{"id": 1, "text": "...", "date": "..."}]}
reminder_counter = 0
notes_counter = 0

# Состояния пользователей
user_state = {}  # {user_id: "main", "reminders", "notes", "chat", "new_note"}
user_chat_history = {}  # {user_id: [{"role": "user/assistant", "content": "..."}]}

# Планировщик
scheduler = None

# Словарь кодов погоды на русском
WEATHER_CODE_RU = {
    0: "☀️ ясно",
    1: "🌤 в основном ясно",
    2: "⛅ переменная облачность",
    3: "☁️ пасмурно",
    45: "🌫 туман",
    48: "🌫 изморозь",
    51: "🌧 морось",
    53: "🌧 морось",
    55: "🌧 сильная морось",
    61: "🌧 небольшой дождь",
    63: "🌧 дождь",
    65: "🌧 сильный дождь",
    71: "🌨 небольшой снег",
    73: "🌨 снег",
    75: "🌨 сильный снег",
    77: "🌨 снежная крупа",
    80: "🌧 ливень",
    81: "🌧 ливень",
    82: "🌧 сильный ливень",
    85: "🌨 снегопад",
    86: "🌨 сильный снегопад",
    95: "⛈ гроза",
    96: "⛈ гроза с градом",
    99: "⛈ сильная гроза",
}

# ================== ФУНКЦИИ СОХРАНЕНИЯ ==================
def save_reminders():
    """Сохраняет напоминания в файл"""
    try:
        save_data = {}
        for uid, reminders in user_reminders.items():
            save_data[str(uid)] = reminders
        
        with open(REMINDERS_FILE, 'w', encoding='utf-8') as f:
            json.dump(save_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"💾 Напоминания сохранены. Всего: {sum(len(v) for v in user_reminders.values())}")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения: {e}")
        return False

def load_reminders():
    """Загружает напоминания из файла"""
    global user_reminders, reminder_counter
    try:
        if os.path.exists(REMINDERS_FILE):
            with open(REMINDERS_FILE, 'r', encoding='utf-8') as f:
                save_data = json.load(f)
            
            user_reminders = {int(k): v for k, v in save_data.items()}
            
            max_id = 0
            for reminders in user_reminders.values():
                for rem in reminders:
                    if rem['id'] > max_id:
                        max_id = rem['id']
            reminder_counter = max_id
            
            logger.info(f"✅ Загружено напоминаний: {sum(len(v) for v in user_reminders.values())}")
        else:
            user_reminders = {}
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки: {e}")
        user_reminders = {}

def save_notes():
    """Сохраняет заметки в файл"""
    try:
        save_data = {}
        for uid, notes in user_notes.items():
            save_data[str(uid)] = notes
        
        with open(NOTES_FILE, 'w', encoding='utf-8') as f:
            json.dump(save_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"💾 Заметки сохранены. Всего: {sum(len(v) for v in user_notes.values())}")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения: {e}")
        return False

def load_notes():
    """Загружает заметки из файла"""
    global user_notes, notes_counter
    try:
        if os.path.exists(NOTES_FILE):
            with open(NOTES_FILE, 'r', encoding='utf-8') as f:
                save_data = json.load(f)
            
            user_notes = {int(k): v for k, v in save_data.items()}
            
            max_id = 0
            for notes in user_notes.values():
                for note in notes:
                    if note['id'] > max_id:
                        max_id = note['id']
            notes_counter = max_id
            
            logger.info(f"✅ Загружено заметок: {sum(len(v) for v in user_notes.values())}")
        else:
            user_notes = {}
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки: {e}")
        user_notes = {}

# ================== ФУНКЦИИ ПОГОДЫ ==================
def geocode_city(city: str) -> dict | None:
    """Получение координат города"""
    url = "https://geocoding-api.open-meteo.com/v1/search"
    params = {"name": city, "count": 1, "language": "ru", "format": "json"}
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        results = data.get("results") or []
        return results[0] if results else None
    except Exception as e:
        logger.error(f"Ошибка геокодинга: {e}")
        return None

def fetch_today_weather(lat: float, lon: float) -> dict:
    """Получение погоды"""
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,weather_code,apparent_temperature",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
        "timezone": "auto",
        "forecast_days": 1,
    }
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    return r.json()

def build_weather_payload(city_label: str, geo: dict, wx: dict) -> dict:
    """Формирование данных о погоде"""
    current = wx.get("current", {}) or {}
    daily = wx.get("daily", {}) or {}
    
    region_parts = []
    if geo.get('admin1'):
        region_parts.append(geo['admin1'])
    if geo.get('country'):
        region_parts.append(geo['country'])
    
    location_full = city_label
    if region_parts:
        location_full = f"{city_label}, {', '.join(region_parts)}"
    
    weather_code = current.get("weather_code")
    weather_desc = WEATHER_CODE_RU.get(weather_code, "🌈 неизвестно")
    
    return {
        "location": location_full,
        "location_short": city_label,
        "temp_now": current.get("temperature_2m"),
        "feels_like": current.get("apparent_temperature"),
        "temp_min": (daily.get("temperature_2m_min") or [None])[0],
        "temp_max": (daily.get("temperature_2m_max") or [None])[0],
        "precip": (daily.get("precipitation_sum") or [0])[0],
        "weather_desc": weather_desc,
        "weather_code": weather_code,
    }

def format_weather_text(payload: dict) -> str:
    """Форматирование текста погоды (запасной вариант)"""
    feels = payload['feels_like']
    feels_text = f" (ощущается как {feels}°C)" if feels else ""
    
    temp = payload['temp_now']
    if temp < -20:
        advice = "🥶 Очень холодно! Одевайся максимально тепло."
    elif temp < -10:
        advice = "🧥 Холодно. Не забудь шапку и перчатки."
    elif temp < 0:
        advice = "🧥 Прохладно. Лучше надеть куртку."
    elif temp < 10:
        advice = "🧥 Свежо. Легкая куртка не помешает."
    elif temp < 20:
        advice = "👕 Комфортная температура. Можно гулять!"
    else:
        advice = "👕 Тепло. Легкая одежда подойдет."
    
    return (
        f"📍 *{payload['location_short']}*\n\n"
        f"🌡️ *Сейчас:* {payload['temp_now']}°C {payload['weather_desc']}{feels_text}\n\n"
        f"📊 *Днем:* от {payload['temp_min']}°C до {payload['temp_max']}°C\n\n"
        f"💧 *Осадки:* {payload['precip']} мм\n\n"
        f"💡 *Совет:* {advice}"
    )

def format_morning_text(payload: dict) -> str:
    """Утреннее приветствие (запасной вариант)"""
    import random
    phrases = ["☀️ Доброе утро!", "🌅 С добрым утром!", "☀️ Просыпайся!"]
    temp_avg = (payload['temp_min'] + payload['temp_max']) // 2
    return (
        f"{random.choice(phrases)}\n\n"
        f"📅 *Прогноз на сегодня:*\n"
        f"{payload['weather_desc']}\n"
        f"🌡️ Средняя температура: {temp_avg}°C\n"
        f"💧 Осадки: {payload['precip']} мм\n\n"
        f"💪 Хорошего дня!"
    )

def format_evening_text(payload: dict) -> str:
    """Вечернее пожелание (запасной вариант)"""
    import random
    phrases = ["🌙 Спокойной ночи!", "✨ Доброй ночи!", "🌙 Сладких снов!"]
    sweet = ["Сны пусть будут радужными! 🌈", "Отдыхай! 💫", "До завтра! ⭐"]
    tomorrow_temp = (payload['temp_min'] + payload['temp_max']) // 2
    return (
        f"{random.choice(phrases)}\n\n"
        f"📊 *Сегодня:* {payload['temp_now']}°C, {payload['weather_desc']}\n"
        f"💫 *Завтра:* ~{tomorrow_temp}°C\n\n"
        f"{random.choice(sweet)}"
    )

async def get_weather_text(payload: dict, text_type: str = "normal") -> str:
    """Получение текста погоды (с Groq если доступен)"""
    if groq_client:
        try:
            if text_type == "morning":
                system = "Ты доброе утро. Напиши короткое утреннее приветствие с прогнозом погоды. Используй данные о погоде. Ответ должен быть тёплым и дружелюбным."
                user = f"В {payload['location_short']} сегодня {payload['temp_min']}-{payload['temp_max']}°C, {payload['weather_desc']}, осадки {payload['precip']} мм."
            elif text_type == "evening":
                system = "Ты нежный и заботливый. Напиши вечернее пожелание спокойной ночи. Упомяни погоду сегодня и коротко на завтра. Добавь ласковые слова."
                user = f"Сегодня было {payload['temp_now']}°C, {payload['weather_desc']}. Завтра {payload['temp_min']}-{payload['temp_max']}°C."
            else:
                system = "Ты дружелюбный помощник. Дай прогноз погоды на сегодня. Используй данные о температуре, осадках и ощущениях."
                user = f"В {payload['location_short']} сейчас {payload['temp_now']}°C, {payload['weather_desc']}, ощущается как {payload['feels_like']}°C. Днем {payload['temp_min']}-{payload['temp_max']}°C, осадки {payload['precip']} мм."

            completion = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                temperature=0.7,
                max_tokens=200,
            )
            groq_text = completion.choices[0].message.content.strip()
            if groq_text and len(groq_text) > 20:
                logger.info(f"✅ Получен ответ от Groq для {text_type}")
                return groq_text
        except Exception as e:
            logger.error(f"❌ Ошибка Groq: {e}")
    
    logger.info(f"📝 Используем локальное форматирование для {text_type}")
    if text_type == "morning":
        return format_morning_text(payload)
    elif text_type == "evening":
        return format_evening_text(payload)
    else:
        return format_weather_text(payload)

# ================== ФУНКЦИИ ЧАТА ==================
async def chat_with_groq(user_id: int, message: str) -> str:
    """Общение с Groq"""
    if not groq_client:
        return "Извини, я сейчас не могу общаться. Проблемы с подключением к нейросети."
    
    try:
        # Сохраняем историю диалога
        if user_id not in user_chat_history:
            user_chat_history[user_id] = [
                {"role": "system", "content": "Ты дружелюбный собеседник. Отвечай кратко, но по делу. Ты общаешься с хорошим другом."}
            ]
        
        # Добавляем сообщение пользователя
        user_chat_history[user_id].append({"role": "user", "content": message})
        
        # Ограничиваем историю последними 10 сообщениями
        if len(user_chat_history[user_id]) > 11:
            user_chat_history[user_id] = [user_chat_history[user_id][0]] + user_chat_history[user_id][-10:]
        
        # Получаем ответ от Groq
        completion = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=user_chat_history[user_id],
            temperature=0.8,
            max_tokens=300,
        )
        
        reply = completion.choices[0].message.content.strip()
        
        # Сохраняем ответ
        user_chat_history[user_id].append({"role": "assistant", "content": reply})
        
        return reply
        
    except Exception as e:
        logger.error(f"❌ Ошибка чата: {e}")
        return "Ой, что-то пошло не так. Давай попробуем еще раз?"

# ================== ФУНКЦИИ НАПОМИНАНИЙ ==================
def parse_time(text: str) -> datetime | None:
    """Парсинг времени из текста с учетом московского времени"""
    now = datetime.now(MSK_TZ)
    text = text.lower().strip()
    
    if 'сегодня' in text:
        match = re.search(r'(\d{1,2}):(\d{2})', text)
        if match:
            return now.replace(hour=int(match.group(1)), minute=int(match.group(2)), second=0, microsecond=0)
    
    if 'завтра' in text:
        match = re.search(r'(\d{1,2})', text)
        if match:
            return (now + timedelta(days=1)).replace(hour=int(match.group(1)), minute=0, second=0, microsecond=0)
    
    match = re.search(r'через\s+(\d+)\s*(час|часа|часов)', text)
    if match:
        return now + timedelta(hours=int(match.group(1)))
    
    if 'через час' in text:
        return now + timedelta(hours=1)
    
    match = re.search(r'через\s+(\d+)\s*(минут|минуты|минуту)', text)
    if match:
        return now + timedelta(minutes=int(match.group(1)))
    
    if 'через минуту' in text:
        return now + timedelta(minutes=1)
    
    match = re.search(r'^(\d{1,2}):(\d{2})$', text)
    if match:
        hour, minute = int(match.group(1)), int(match.group(2))
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return candidate if candidate > now else candidate + timedelta(days=1)
    
    return None

async def send_reminder(bot, user_id: int, text: str, reminder_id: int):
    """Отправка напоминания"""
    try:
        await bot.send_message(
            chat_id=user_id,
            text=f"⏰ *НАПОМИНАНИЕ!*\n\n{text}",
            parse_mode='Markdown'
        )
        logger.info(f"✅ Напоминание {reminder_id} отправлено")
        
        if user_id in user_reminders:
            user_reminders[user_id] = [r for r in user_reminders[user_id] if r['id'] != reminder_id]
            save_reminders()
            
    except Exception as e:
        logger.error(f"Ошибка отправки: {e}")

# ================== РАССЫЛКИ ==================
async def send_morning_forecast(bot):
    """Утренняя рассылка в 8:00"""
    now = datetime.now(MSK_TZ)
    logger.info(f"⏰ Утренняя рассылка в {now.strftime('%H:%M')}")
    
    if not user_cities:
        logger.info("Нет пользователей для рассылки")
        return
    
    for user_id, city in user_cities.items():
        try:
            geo = geocode_city(city)
            if not geo:
                continue
            wx = fetch_today_weather(geo["latitude"], geo["longitude"])
            payload = build_weather_payload(geo.get("name", city), geo, wx)
            text = await get_weather_text(payload, "morning")
            await bot.send_message(chat_id=user_id, text=text, parse_mode='Markdown')
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.error(f"Ошибка: {e}")

async def send_evening_message(bot):
    """Вечерняя рассылка в 22:00"""
    now = datetime.now(MSK_TZ)
    logger.info(f"🌙 Вечерняя рассылка в {now.strftime('%H:%M')}")
    
    if not user_cities:
        logger.info("Нет пользователей для рассылки")
        return
    
    for user_id, city in user_cities.items():
        try:
            geo = geocode_city(city)
            if not geo:
                continue
            wx = fetch_today_weather(geo["latitude"], geo["longitude"])
            payload = build_weather_payload(geo.get("name", city), geo, wx)
            text = await get_weather_text(payload, "evening")
            await bot.send_message(chat_id=user_id, text=text, parse_mode='Markdown')
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.error(f"Ошибка: {e}")

# ================== ОБРАБОТЧИКИ ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка /start"""
    user = update.effective_user
    user_id = user.id
    logger.info(f"👉 /start от @{user.username}")
    
    user_state[user_id] = "main"
    if user_id in context.user_data:
        context.user_data.clear()
    
    await update.message.reply_text(
        f"👋 *Привет, {user.first_name}!*\n\n"
        f"Я твой личный помощник. Что умею:\n"
        f"🌤️ *Погода* - узнай прогноз в любом городе\n"
        f"⏰ *Напоминания* - не дам забыть о важном\n"
        f"📝 *Заметки* - сохраняй свои мысли\n"
        f"💬 *Поболтать* - просто поговори со мной\n\n"
        f"Выбирай кнопку в меню!",
        reply_markup=main_keyboard,
        parse_mode='Markdown'
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка всех сообщений"""
    text = update.message.text.strip()
    user = update.effective_user
    user_id = user.id
    
    logger.info(f"📨 Сообщение от @{user.username}: '{text}'")
    
    # ===== ГЛАВНЫЕ КНОПКИ =====
    if text == BTN_START:
        logger.info("🔴 Погода")
        user_state[user_id] = "main"
        if user_id in user_cities:
            del user_cities[user_id]
        await update.message.reply_text("Введи название города:", reply_markup=main_keyboard)
        return
    
    if text == BTN_UPDATE:
        logger.info("🟢 Обновить прогноз")
        user_state[user_id] = "main"
        if user_id not in user_cities:
            await update.message.reply_text("Сначала введи город!", reply_markup=main_keyboard)
            return
        await update.message.reply_text(f"🔄 Обновляю прогноз...", reply_markup=main_keyboard)
        await send_weather(update, user_cities[user_id])
        return
    
    if text == BTN_REMINDERS:
        logger.info("🔵 Напоминания")
        user_state[user_id] = "reminders"
        await update.message.reply_text(
            "📌 *Напоминания*\n\nВыбери действие:", 
            parse_mode='Markdown', 
            reply_markup=reminders_keyboard
        )
        return
    
    if text == BTN_NOTES:
        logger.info("📗 Заметки")
        user_state[user_id] = "notes"
        await update.message.reply_text(
            "📝 *Мои заметки*\n\nВыбери действие:",
            parse_mode='Markdown',
            reply_markup=notes_keyboard
        )
        return
    
    if text == BTN_CHAT:
        logger.info("💬 Чат")
        user_state[user_id] = "chat"
        await update.message.reply_text(
            "💬 *Давай поболтаем!*\n\nПиши что хочешь, я отвечу. Для выхода нажми /start",
            parse_mode='Markdown'
        )
        return
    
    # ===== РЕЖИМ ЧАТА =====
    if user_state.get(user_id) == "chat":
        logger.info(f"💬 Чат от @{user.username}: {text}")
        
        if text.lower() in ['выход', 'стоп', 'хватит', 'назад']:
            user_state[user_id] = "main"
            await update.message.reply_text("Возвращаюсь в главное меню:", reply_markup=main_keyboard)
            return
        
        # Отправляем "печатает..."
        await update.message.chat.send_action(action="typing")
        
        # Получаем ответ от Groq
        reply = await chat_with_groq(user_id, text)
        
        await update.message.reply_text(reply)
        return
    
    # ===== РЕЖИМ НАПОМИНАНИЙ =====
    if user_state.get(user_id) == "reminders":
        if text == "🔙 Назад":
            user_state[user_id] = "main"
            await update.message.reply_text("Главное меню:", reply_markup=main_keyboard)
            return
        
        if text == "📝 Создать":
            await update.message.reply_text(
                "🕐 *Создание напоминания*\n\n"
                "Формат: `Текст | время`\n\n"
                "Примеры:\n"
                "• `Позвонить маме | 15:30`\n"
                "• `Выпить таблетки | завтра в 9`\n"
                "• `Сходить в магазин | через 2 часа`\n"
                "• `Напоминание | через час`",
                parse_mode='Markdown'
            )
            context.user_data['awaiting_reminder'] = True
            return
        
        if text == "📋 Список":
            if user_id not in user_reminders or not user_reminders[user_id]:
                await update.message.reply_text("📋 У тебя нет напоминаний.", reply_markup=reminders_keyboard)
                return
            
            response = "📋 *Твои напоминания:*\n\n"
            for i, rem in enumerate(user_reminders[user_id], 1):
                rem_time = datetime.fromisoformat(rem['time'])
                if rem_time.tzinfo is None:
                    rem_time = MSK_TZ.localize(rem_time)
                t = rem_time.strftime("%d.%m %H:%M")
                response += f"{i}. 🕐 *{t}*\n   {rem['text']}\n\n"
            
            await update.message.reply_text(response, parse_mode='Markdown', reply_markup=reminders_keyboard)
            return
        
        if text == "❌ Удалить":
            if user_id not in user_reminders or not user_reminders[user_id]:
                await update.message.reply_text("Нет напоминаний.", reply_markup=reminders_keyboard)
                return
            kb = []
            for rem in user_reminders[user_id]:
                rem_time = datetime.fromisoformat(rem['time'])
                if rem_time.tzinfo is None:
                    rem_time = MSK_TZ.localize(rem_time)
                t = rem_time.strftime("%d.%m %H:%M")
                kb.append([f"❌ {t} - {rem['text'][:15]}"])
            kb.append(["🔙 Назад"])
            await update.message.reply_text(
                "Выбери для удаления:", 
                reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True)
            )
            context.user_data['deleting_reminder'] = True
            return
        
        # ===== СОЗДАНИЕ НАПОМИНАНИЯ =====
        if context.user_data.get('awaiting_reminder'):
            if '|' not in text:
                await update.message.reply_text("❌ Формат: `Текст | время`", parse_mode='Markdown')
                return
            
            parts = text.split('|')
            reminder_text = parts[0].strip()
            time_text = parts[1].strip()
            reminder_time = parse_time(time_text)
            
            if not reminder_time:
                await update.message.reply_text("❌ Не понял время. Попробуй: 15:30, завтра в 9, через 2 часа, через час")
                return
            
            global reminder_counter
            reminder_counter += 1
            
            global scheduler
            if scheduler:
                job = scheduler.add_job(
                    send_reminder,
                    'date',
                    run_date=reminder_time,
                    args=[context.application.bot, user_id, reminder_text, reminder_counter]
                )
                
                if user_id not in user_reminders:
                    user_reminders[user_id] = []
                
                user_reminders[user_id].append({
                    'id': reminder_counter,
                    'text': reminder_text,
                    'time': reminder_time.isoformat(),
                    'job_id': job.id
                })
                
                save_reminders()
                
                context.user_data['awaiting_reminder'] = False
                await update.message.reply_text(
                    f"✅ *Напоминание создано!*\n\n📝 {reminder_text}\n🕐 {reminder_time.strftime('%d.%m.%Y %H:%M')}",
                    parse_mode='Markdown',
                    reply_markup=reminders_keyboard
                )
            else:
                await update.message.reply_text("❌ Ошибка планировщика. Попробуй позже.")
            return
        
        # ===== УДАЛЕНИЕ НАПОМИНАНИЯ =====
        if context.user_data.get('deleting_reminder'):
            if text == "🔙 Назад":
                context.user_data['deleting_reminder'] = False
                await update.message.reply_text("Меню напоминаний:", reply_markup=reminders_keyboard)
                return
            
            if user_id in user_reminders:
                for rem in user_reminders[user_id][:]:
                    rem_time = datetime.fromisoformat(rem['time'])
                    if rem_time.tzinfo is None:
                        rem_time = MSK_TZ.localize(rem_time)
                    preview = f"❌ {rem_time.strftime('%d.%m %H:%M')} - {rem['text'][:15]}"
                    if preview == text:
                        try:
                            if scheduler:
                                scheduler.remove_job(rem['job_id'])
                        except:
                            pass
                        user_reminders[user_id].remove(rem)
                        save_reminders()
                        await update.message.reply_text("✅ Удалено!", reply_markup=reminders_keyboard)
                        context.user_data['deleting_reminder'] = False
                        return
            
            await update.message.reply_text("❌ Не найдено", reply_markup=reminders_keyboard)
            context.user_data['deleting_reminder'] = False
            return
        
        await update.message.reply_text("Используй кнопки меню напоминаний.", reply_markup=reminders_keyboard)
        return
    
    # ===== РЕЖИМ ЗАМЕТОК =====
    if user_state.get(user_id) == "notes":
        if text == "🔙 Назад":
            user_state[user_id] = "main"
            await update.message.reply_text("Главное меню:", reply_markup=main_keyboard)
            return
        
        if text == "📝 Новая заметка":
            user_state[user_id] = "new_note"
            await update.message.reply_text(
                "📝 *Новая заметка*\n\nПросто напиши текст заметки:",
                parse_mode='Markdown'
            )
            return
        
        if text == "📋 Все заметки":
            if user_id not in user_notes or not user_notes[user_id]:
                await update.message.reply_text("📭 У тебя пока нет заметок.", reply_markup=notes_keyboard)
                return
            
            response = "📚 *Твои заметки:*\n\n"
            for i, note in enumerate(reversed(user_notes[user_id][-10:]), 1):
                note_date = datetime.fromisoformat(note['date']).strftime("%d.%m")
                response += f"{i}. 📝 *{note_date}*\n   {note['text'][:50]}...\n\n"
            
            response += "_Показаны последние 10 заметок_"
            await update.message.reply_text(response, parse_mode='Markdown', reply_markup=notes_keyboard)
            return
        
        if text == "❌ Удалить заметку":
            if user_id not in user_notes or not user_notes[user_id]:
                await update.message.reply_text("Нет заметок.", reply_markup=notes_keyboard)
                return
            
            kb = []
            for note in reversed(user_notes[user_id][-5:]):
                note_date = datetime.fromisoformat(note['date']).strftime("%d.%m")
                preview = note['text'][:30]
                kb.append([f"❌ {note_date} - {preview}"])
            kb.append(["🔙 Назад"])
            
            await update.message.reply_text(
                "Выбери заметку для удаления (последние 5):",
                reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True)
            )
            context.user_data['deleting_note'] = True
            return
        
        return
    
    # ===== СОЗДАНИЕ НОВОЙ ЗАМЕТКИ =====
    if user_state.get(user_id) == "new_note":
        logger.info(f"📝 Новая заметка от @{user.username}: {text[:50]}...")
        
        global notes_counter
        notes_counter += 1
        
        if user_id not in user_notes:
            user_notes[user_id] = []
        
        user_notes[user_id].append({
            'id': notes_counter,
            'text': text,
            'date': datetime.now(MSK_TZ).isoformat()
        })
        
        save_notes()
        
        user_state[user_id] = "notes"
        await update.message.reply_text(
            "✅ *Заметка сохранена!*",
            parse_mode='Markdown',
            reply_markup=notes_keyboard
        )
        return
    
    # ===== УДАЛЕНИЕ ЗАМЕТКИ =====
    if context.user_data.get('deleting_note'):
        if text == "🔙 Назад":
            context.user_data['deleting_note'] = False
            await update.message.reply_text("Меню заметок:", reply_markup=notes_keyboard)
            return
        
        if user_id in user_notes:
            for note in user_notes[user_id][:]:
                note_date = datetime.fromisoformat(note['date']).strftime("%d.%m")
                preview = note['text'][:30]
                if f"❌ {note_date} - {preview}" == text:
                    user_notes[user_id].remove(note)
                    save_notes()
                    await update.message.reply_text("✅ Заметка удалена!", reply_markup=notes_keyboard)
                    context.user_data['deleting_note'] = False
                    return
        
        await update.message.reply_text("❌ Не найдено", reply_markup=notes_keyboard)
        context.user_data['deleting_note'] = False
        return
    
    # ===== ВВОД ГОРОДА =====
    logger.info(f"🏙️ Ввод города: {text}")
    user_state[user_id] = "main"
    user_cities[user_id] = text
    await update.message.reply_text(f"🔍 Ищу погоду для {text}...", reply_markup=main_keyboard)
    await send_weather(update, text)

async def send_weather(update: Update, city: str):
    """Отправка прогноза"""
    try:
        geo = geocode_city(city)
        if not geo:
            await update.message.reply_text(f"❌ Город '{city}' не найден.", reply_markup=main_keyboard)
            return
        
        wx = fetch_today_weather(geo["latitude"], geo["longitude"])
        payload = build_weather_payload(geo.get("name", city), geo, wx)
        text = await get_weather_text(payload, "normal")
        
        await update.message.reply_text(text, reply_markup=main_keyboard, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        await update.message.reply_text("❌ Ошибка. Попробуй позже.", reply_markup=main_keyboard)

# ================== ЗАПУСК ==================
async def main():
    global scheduler
    logger.info("🚀 Запуск бота...")
    
    # Загружаем сохраненные данные
    load_reminders()
    load_notes()
    
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    
    # Создаем планировщик
    scheduler = AsyncIOScheduler(timezone=str(MSK_TZ))
    scheduler.add_job(send_morning_forecast, CronTrigger(hour=8, minute=0, timezone=MSK_TZ), args=[app.bot])
    scheduler.add_job(send_evening_message, CronTrigger(hour=22, minute=0, timezone=MSK_TZ), args=[app.bot])
    scheduler.start()
    
    # Восстанавливаем напоминания
    restored = 0
    for user_id, reminders in user_reminders.items():
        for rem in reminders:
            try:
                reminder_time = datetime.fromisoformat(rem['time'])
                if reminder_time.tzinfo is None:
                    reminder_time = MSK_TZ.localize(reminder_time)
                
                if reminder_time > datetime.now(MSK_TZ):
                    job = scheduler.add_job(
                        send_reminder,
                        'date',
                        run_date=reminder_time,
                        args=[app.bot, user_id, rem['text'], rem['id']],
                        id=rem['job_id']
                    )
                    rem['job_id'] = job.id
                    restored += 1
                else:
                    user_reminders[user_id].remove(rem)
            except Exception as e:
                logger.error(f"❌ Ошибка восстановления: {e}")
    
    logger.info(f"🔄 Восстановлено напоминаний: {restored}")
    save_reminders()
    logger.info("✅ Бот запущен! Планировщик работает.")
    
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass
    finally:
        scheduler.shutdown()
        await app.stop()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Бот остановлен")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
        raise
