def format_evening_text(payload: dict) -> str:

    greeting = random.choice(EVENING_GREETINGS)
    wish = random.choice(EVENING_WISHES)

    tomorrow_temp = "—"
    if payload.get('temp_min') is not None and payload.get('temp_max') is not None:
        tomorrow_temp = int((payload['temp_min'] + payload['temp_max']) / 2)

    wind = payload.get("wind_speed")
    wind_line = f"🌬️ Ветер сейчас: {wind} м/с\n" if wind is not None else ""

    variants = []

    variants.append(
        f"""{greeting}

📊 Сегодня было:
🌡 {payload['temp_now']}°C
{payload['weather_desc']}

{wind_line}
🌤 Завтра ожидается около {tomorrow_temp}°C

{wish}"""
    )

    variants.append(
        f"""{greeting}

📍 {payload['location_short']}

Сегодня:
{payload['weather_desc']}
🌡 {payload['temp_now']}°C

🌤 Завтра около {tomorrow_temp}°C

{wish}"""
    )

    variants.append(
        f"""{greeting}

День заканчивается.

Сегодня:
{payload['weather_desc']}
🌡 {payload['temp_now']}°C

Завтра примерно {tomorrow_temp}°C.

{wish}"""
    )

    text = random.choice(variants)

    return _append_minmax_stats(text, payload)
