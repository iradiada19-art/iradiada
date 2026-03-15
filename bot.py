#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import asyncio
import logging
import requests
import re
import random

from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from pytz import timezone

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# =========================================================
# НАСТРОЙКИ
# =========================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

MSK_TZ = timezone("Europe/Moscow")

REMINDERS_FILE = "/tmp/reminders.json"
NOTES_FILE = "/tmp/notes.json"
WEATHER_HISTORY_FILE = "/tmp/weather_history.json"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =========================================================
# КНОПКИ
# =========================================================

BTN_WEATHER = "Узнать погоду"
BTN_UPDATE = "Обновить прогноз"
BTN_REMINDERS = "Напоминания"
BTN_NOTES = "Мои заметки"

main_keyboard = ReplyKeyboardMarkup(
    [[BTN_WEATHER, BTN_UPDATE], [BTN_REMINDERS, BTN_NOTES]],
    resize_keyboard=True
)

# =========================================================
# ДАННЫЕ
# =========================================================

user_cities = {}
user_reminders = {}
user_notes = {}

scheduler = None

# =========================================================
# ФРАЗЫ
# =========================================================

MORNING_GREETINGS = [
    "☀️ Доброе утро!",
    "🌅 С добрым утром!",
    "🌞 Новый день начинается!",
    "🌸 Доброе утро! Пусть всё получится.",
    "🌤 Отличного начала дня!"
]

EVENING_GREETINGS = [
    "🌙 Спокойной ночи!",
    "✨ Доброй ночи!",
    "🌜 Отдыхай — завтра новый день.",
    "🌠 Сладких снов!"
]

# =========================================================
# JSON УТИЛИТЫ
# =========================================================

def load_json(path):

    if not os.path.exists(path):
        return {}

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# =========================================================
# ПОГОДА
# =========================================================

def geocode_city(city):

    url = "https://geocoding-api.open-meteo.com/v1/search"

    params = {
        "name": city,
        "count": 1,
        "language": "ru"
    }

    r = requests.get(url, params=params, timeout=10)

    data = r.json()

    if not data.get("results"):
        return None

    return data["results"][0]


def fetch_weather(lat, lon):

    url = "https://api.open-meteo.com/v1/forecast"

    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,weather_code,wind_speed_10m",
        "daily": "temperature_2m_min,temperature_2m_max",
        "forecast_days": 1,
        "timezone": "auto"
    }

    r = requests.get(url, params=params, timeout=10)

    return r.json()

# =========================================================
# СТАТИСТИКА ПОГОДЫ
# =========================================================

def save_weather_day(city, tmin, tmax):

    history = load_json(WEATHER_HISTORY_FILE)

    city = city.lower()

    if city not in history:
        history[city] = []

    today = datetime.now().strftime("%Y-%m-%d")

    for rec in history[city]:

        if rec["date"] == today:
            return

    history[city].append({
        "date": today,
        "min": tmin,
        "max": tmax
    })

    save_json(WEATHER_HISTORY_FILE, history)


def get_weather_stats(city):

    history = load_json(WEATHER_HISTORY_FILE)

    city = city.lower()

    if city not in history:
        return None

    mins = [x["min"] for x in history[city]]
    maxs = [x["max"] for x in history[city]]

    return {
        "min": min(mins),
        "max": max(maxs),
        "count": len(history[city])
    }

# =========================================================
# ФОРМАТ ПОГОДЫ
# =========================================================

def format_weather(city, wx):

    current = wx["current"]
    daily = wx["daily"]

    temp = current["temperature_2m"]
    wind = current["wind_speed_10m"]

    tmin = daily["temperature_2m_min"][0]
    tmax = daily["temperature_2m_max"][0]

    save_weather_day(city, tmin, tmax)

    stats = get_weather_stats(city)

    stats_text = ""

    if stats:

        stats_text = (
            "\n\n📊 *Статистика за годы*\n"
            f"минимум: {stats['min']}°C\n"
            f"максимум: {stats['max']}°C\n"
            f"дней в базе: {stats['count']}"
        )

    return (
        f"📍 *{city}*\n\n"
        f"🌡 Сейчас: {temp}°C\n"
        f"🌬 Ветер: {wind} м/с\n\n"
        f"Сегодня:\n"
        f"минимум {tmin}°C\n"
        f"максимум {tmax}°C"
        f"{stats_text}"
    )

# =========================================================
# КОМАНДЫ
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "Привет! Напиши название города.",
        reply_markup=main_keyboard
    )


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    if user_id not in user_cities:
        await update.message.reply_text("Сначала укажи город")
        return

    city = user_cities[user_id]

    stats = get_weather_stats(city)

    if not stats:

        await update.message.reply_text("Статистика пока не накоплена")
        return

    await update.message.reply_text(

        f"📊 Статистика {city}\n\n"
        f"🌡 минимум: {stats['min']}°C\n"
        f"🔥 максимум: {stats['max']}°C\n"
        f"📅 дней в базе: {stats['count']}"

    )

# =========================================================
# ТЕКСТ
# =========================================================

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):

    text = update.message.text.strip()

    user_id = update.effective_user.id

    geo = geocode_city(text)

    if not geo:

        await update.message.reply_text("Город не найден")
        return

    user_cities[user_id] = text

    wx = fetch_weather(geo["latitude"], geo["longitude"])

    msg = format_weather(text, wx)

    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=main_keyboard)

# =========================================================
# РАССЫЛКИ
# =========================================================

async def morning_job(bot):

    for user_id, city in user_cities.items():

        geo = geocode_city(city)

        if not geo:
            continue

        wx = fetch_weather(geo["latitude"], geo["longitude"])

        greet = random.choice(MORNING_GREETINGS)

        daily = wx["daily"]

        msg = (
            f"{greet}\n\n"
            f"{city}\n"
            f"{daily['temperature_2m_min'][0]}..{daily['temperature_2m_max'][0]}°C"
        )

        await bot.send_message(user_id, msg)


async def evening_job(bot):

    for user_id, city in user_cities.items():

        geo = geocode_city(city)

        if not geo:
            continue

        wx = fetch_weather(geo["latitude"], geo["longitude"])

        greet = random.choice(EVENING_GREETINGS)

        temp = wx["current"]["temperature_2m"]

        msg = (
            f"{greet}\n\n"
            f"Сегодня было около {temp}°C"
        )

        await bot.send_message(user_id, msg)

# =========================================================
# MAIN
# =========================================================

async def main():

    global scheduler

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    scheduler = AsyncIOScheduler(timezone=str(MSK_TZ))

    scheduler.add_job(
        morning_job,
        CronTrigger(hour=8, minute=0),
        args=[app.bot]
    )

    scheduler.add_job(
        evening_job,
        CronTrigger(hour=22, minute=0),
        args=[app.bot]
    )

    scheduler.start()

    logger.info("Бот запущен")

    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
