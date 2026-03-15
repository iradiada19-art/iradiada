#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import asyncio
import logging
import random
import re
import requests

from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from pytz import timezone

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# =========================================================
# CONFIG
# =========================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN не найден")

MSK_TZ = timezone("Europe/Moscow")

DATA_DIR = "/tmp"

REMINDERS_FILE = f"{DATA_DIR}/reminders.json"
NOTES_FILE = f"{DATA_DIR}/notes.json"
STATS_FILE = f"{DATA_DIR}/weather_stats.json"

# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)

# =========================================================
# KEYBOARDS
# =========================================================

BTN_WEATHER = "Погода"
BTN_UPDATE = "Обновить"
BTN_REMINDERS = "Напоминания"
BTN_NOTES = "Заметки"

main_keyboard = ReplyKeyboardMarkup(
    [
        [BTN_WEATHER, BTN_UPDATE],
        [BTN_REMINDERS, BTN_NOTES]
    ],
    resize_keyboard=True
)

# =========================================================
# DATA
# =========================================================

user_cities = {}

user_reminders = {}
user_notes = {}

weather_stats = {}

reminder_counter = 0
note_counter = 0

scheduler = None

# =========================================================
# PHRASES
# =========================================================

MORNING_GREETINGS = [
    "☀️ Доброе утро!",
    "🌅 С добрым утром!",
    "🌞 Новый день начинается!",
    "🌤 Доброе утро! Пусть день будет лёгким.",
    "🌸 Просыпайся — впереди хороший день.",
    "🌼 Доброе утро! Пусть всё получится.",
]

MORNING_WISHES = [
    "💪 Пусть сегодня всё сложится удачно.",
    "🌟 Хорошего дня!",
    "🚀 Пусть день будет продуктивным.",
    "🍀 Удачи во всех делах.",
]

EVENING_GREETINGS = [
    "🌙 Спокойной ночи!",
    "✨ Доброй ночи!",
    "🌜 Время отдыхать.",
    "🌠 Сладких снов!",
]

EVENING_WISHES = [
    "💤 Пусть сон будет крепким.",
    "⭐ Отдыхай и набирайся сил.",
    "🌙 До завтра.",
]

# =========================================================
# FILE UTILS
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
# WEATHER
# =========================================================

def geocode(city):

    url = "https://geocoding-api.open-meteo.com/v1/search"

    params = {
        "name": city,
        "count": 1,
        "language": "ru"
    }

    r = requests.get(url, params=params, timeout=15)

    data = r.json()

    if not data.get("results"):
        return None

    return data["results"][0]


def get_weather(lat, lon, days=1):

    url = "https://api.open-meteo.com/v1/forecast"

    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,weather_code,wind_speed_10m",
        "daily": "temperature_2m_min,temperature_2m_max,precipitation_sum",
        "forecast_days": days,
        "timezone": "auto"
    }

    r = requests.get(url, params=params, timeout=15)

    return r.json()

# =========================================================
# WEATHER STATS
# =========================================================

def update_weather_stats(city, temp):

    city = city.lower()

    if city not in weather_stats:

        weather_stats[city] = {
            "min": temp,
            "max": temp
        }

    else:

        weather_stats[city]["min"] = min(weather_stats[city]["min"], temp)
        weather_stats[city]["max"] = max(weather_stats[city]["max"], temp)

    save_json(STATS_FILE, weather_stats)


def get_weather_stats(city):

    city = city.lower()

    if city not in weather_stats:
        return None

    return weather_stats[city]

# =========================================================
# FORMATTERS
# =========================================================

def format_weather(city, payload):

    current = payload["current"]
    daily = payload["daily"]

    temp = current["temperature_2m"]

    tmin = daily["temperature_2m_min"][0]
    tmax = daily["temperature_2m_max"][0]

    wind = current["wind_speed_10m"]

    update_weather_stats(city, temp)

    stats = get_weather_stats(city)

    stats_text = ""

    if stats:

        stats_text = (
            "\n\n📊 Историческая статистика\n"
            f"минимум: {stats['min']}°C\n"
            f"максимум: {stats['max']}°C"
        )

    return (
        f"📍 {city}\n\n"
        f"🌡 Сейчас: {temp}°C\n"
        f"🌬 Ветер: {wind} м/с\n\n"
        f"Сегодня:\n"
        f"минимум {tmin}°C\n"
        f"максимум {tmax}°C"
        f"{stats_text}"
    )


def format_morning(city, payload):

    greet = random.choice(MORNING_GREETINGS)
    wish = random.choice(MORNING_WISHES)

    daily = payload["daily"]

    tmin = daily["temperature_2m_min"][0]
    tmax = daily["temperature_2m_max"][0]

    return (
        f"{greet}\n\n"
        f"Сегодня в {city}:\n"
        f"🌡 {tmin}..{tmax}°C\n\n"
        f"{wish}"
    )


def format_evening(city, payload):

    greet = random.choice(EVENING_GREETINGS)
    wish = random.choice(EVENING_WISHES)

    current = payload["current"]

    return (
        f"{greet}\n\n"
        f"Сегодня было:\n"
        f"🌡 {current['temperature_2m']}°C\n\n"
        f"{wish}"
    )

# =========================================================
# HANDLERS
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "Я погодный помощник ☀️\n\n"
        "Отправь название города.",
        reply_markup=main_keyboard
    )


async def weather_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "Напиши название города"
    )


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    if user_id not in user_cities:

        await update.message.reply_text("Сначала укажи город")
        return

    city = user_cities[user_id]

    stats = get_weather_stats(city)

    if not stats:

        await update.message.reply_text("Статистика пока не собрана")
        return

    await update.message.reply_text(

        f"📊 Статистика {city}\n\n"
        f"минимум: {stats['min']}°C\n"
        f"максимум: {stats['max']}°C"

    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):

    text = update.message.text.strip()

    user_id = update.effective_user.id

    geo = geocode(text)

    if not geo:

        await update.message.reply_text("Город не найден")
        return

    user_cities[user_id] = text

    weather = get_weather(geo["latitude"], geo["longitude"])

    msg = format_weather(text, weather)

    await update.message.reply_text(msg, reply_markup=main_keyboard)

# =========================================================
# BROADCASTS
# =========================================================

async def morning_job(bot):

    for user_id, city in user_cities.items():

        geo = geocode(city)

        if not geo:
            continue

        wx = get_weather(geo["latitude"], geo["longitude"])

        text = format_morning(city, wx)

        await bot.send_message(user_id, text)


async def evening_job(bot):

    for user_id, city in user_cities.items():

        geo = geocode(city)

        if not geo:
            continue

        wx = get_weather(geo["latitude"], geo["longitude"])

        text = format_evening(city, wx)

        await bot.send_message(user_id, text)

# =========================================================
# MAIN
# =========================================================

async def main():

    global scheduler
    global weather_stats

    weather_stats = load_json(STATS_FILE)

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("weather", weather_command))
    app.add_handler(CommandHandler("stats", stats_command))

    app.add_handler(MessageHandler(filters.TEXT, handle_text))

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
