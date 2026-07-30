"""
Telegram Bot + Mini App для записи к массажисту
Один файл — бот (aiogram), API (FastAPI), база данных (SQLite)
"""

import os
import sys
import json
import hashlib
import hmac
import secrets
import logging
import asyncio
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager

# Загружаем .env файл если он есть (локальная разработка)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    WebAppInfo, ReplyKeyboardMarkup, KeyboardButton
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

import aiosqlite
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

# ============= НАСТРОЙКИ =============

BOT_TOKEN = os.getenv("BOT_TOKEN", "ВАШ_ТОКЕН_БОТА")
SECRET_KEY = os.getenv("SECRET_KEY", "супер_секретный_ключ_смени_меня")
# Порт для Railway (они задают PORT, по умолчанию 8000)
PORT = int(os.getenv("PORT", "8000"))
# URL Mini App — задан жёстко, чтобы работало всегда
# Если хочешь сменить домен — поменяй здесь или задай WEBAPP_URL в .env
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://bot-tg-production-f2f4.up.railway.app")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "0").split(",")))  # ID админов через запятую

BASEDIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASEDIR, "bot.db")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============= БАЗА ДАННЫХ =============

async def init_db():
    """Создание таблиц при первом запуске"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.execute("PRAGMA foreign_keys=ON;")
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE NOT NULL,
                username TEXT,
                full_name TEXT,
                phone TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS services (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                price INTEGER NOT NULL,
                duration INTEGER NOT NULL DEFAULT 60,
                is_active INTEGER DEFAULT 1
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS appointments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                service_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                time TEXT NOT NULL,
                status TEXT DEFAULT 'confirmed',
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (service_id) REFERENCES services(id)
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS wheel_spins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                spin_date TEXT NOT NULL,
                prize TEXT NOT NULL,
                claimed INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS wheel_prizes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                probability REAL NOT NULL,
                color TEXT DEFAULT '#FF6B6B',
                is_active INTEGER DEFAULT 1
            )
        """)
        
        await db.commit()
        
        # Заполняем тестовые данные если таблицы пустые
        cursor = await db.execute("SELECT COUNT(*) FROM services")
        count = await cursor.fetchone()
        if count and count[0] == 0:
            services = [
                ("Классический массаж спины", "Расслабляющий массаж всего тела", 2500, 60),
                ("Массаж шеи и воротниковой зоны", "Снятие напряжения в шее и плечах", 1500, 30),
                ("Общий массаж тела", "Полный массаж с головы до ног", 4000, 90),
                ("Антицеллюлитный массаж", "Массаж проблемных зон", 3000, 60),
                ("Спортивный массаж", "Восстановительный массаж для мышц", 3500, 60),
            ]
            await db.executemany(
                "INSERT INTO services (name, description, price, duration) VALUES (?, ?, ?, ?)",
                services
            )
            
            prizes = [
                ("Скидка 10%", "Скидка на любой массаж", 0.30, "#FF6B6B"),
                ("Скидка 20%", "Скидка на любой массаж", 0.15, "#4ECDC4"),
                ("Бесплатная консультация", "15-минутная консультация", 0.20, "#45B7D1"),
                ("+15 минут к сеансу", "Бесплатные 15 минут к массажу", 0.20, "#96CEB4"),
                ("Попробуй снова", "Повезет в следующий раз", 0.10, "#DDA0DD"),
                ("Скидка 50%", "Главный приз — половина цены", 0.05, "#FFD700"),
            ]
            await db.executemany(
                "INSERT INTO wheel_prizes (name, description, probability, color) VALUES (?, ?, ?, ?)",
                prizes
            )
            
            await db.commit()


async def get_or_create_user(telegram_id: int, username: str = None, full_name: str = None):
    """Получить или создать пользователя"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys=ON;")
        cursor = await db.execute("SELECT id, telegram_id, username, full_name, phone FROM users WHERE telegram_id = ?", (telegram_id,))
        user = await cursor.fetchone()
        
        if user:
            return {"id": user[0], "telegram_id": user[1], "username": user[2], "full_name": user[3], "phone": user[4]}
        
        await db.execute(
            "INSERT INTO users (telegram_id, username, full_name) VALUES (?, ?, ?)",
            (telegram_id, username, full_name)
        )
        await db.commit()
        
        cursor = await db.execute("SELECT id, telegram_id, username, full_name, phone FROM users WHERE telegram_id = ?", (telegram_id,))
        user = await cursor.fetchone()
        return {"id": user[0], "telegram_id": user[1], "username": user[2], "full_name": user[3], "phone": user[4]}


async def get_services():
    """Получить список активных услуг"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT id, name, description, price, duration FROM services WHERE is_active = 1 ORDER BY price"
        )
        rows = await cursor.fetchall()
        return [
            {"id": r[0], "name": r[1], "description": r[2], "price": r[3], "duration": r[4]}
            for r in rows
        ]


async def create_appointment(user_id: int, service_id: int, date: str, time: str):
    """Создать запись"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys=ON;")
        
        # Проверяем нет ли уже записи на это время
        cursor = await db.execute(
            "SELECT id FROM appointments WHERE date = ? AND time = ? AND status = 'confirmed'",
            (date, time)
        )
        existing = await cursor.fetchone()
        if existing:
            return {"error": "Это время уже занято"}
        
        await db.execute(
            "INSERT INTO appointments (user_id, service_id, date, time) VALUES (?, ?, ?, ?)",
            (user_id, service_id, date, time)
        )
        await db.commit()
        return {"success": True}


async def get_user_appointments(user_id: int):
    """Получить записи пользователя"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT a.id, s.name, a.date, a.time, a.status
            FROM appointments a
            JOIN services s ON a.service_id = s.id
            WHERE a.user_id = ?
            ORDER BY a.date DESC, a.time DESC
            LIMIT 20
        """, (user_id,))
        rows = await cursor.fetchall()
        return [
            {"id": r[0], "service": r[1], "date": r[2], "time": r[3], "status": r[4]}
            for r in rows
        ]


async def can_spin_wheel(user_id: int):
    """Проверить можно ли крутить колесо (раз в 24 часа)"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT spin_date FROM wheel_spins WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            (user_id,)
        )
        last_spin = await cursor.fetchone()
        
        if not last_spin:
            return True, 0
        
        last_time = datetime.strptime(last_spin[0], "%Y-%m-%d %H:%M:%S.%f")
        last_time = last_time.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        diff = now - last_time
        
        if diff.total_seconds() < 86400:
            remaining = int(86400 - diff.total_seconds())
            return False, remaining
        
        return True, 0


async def spin_wheel(user_id: int):
    """Крутить колесо — сервер выбирает приз по вероятности"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys=ON;")
        
        cursor = await db.execute(
            "SELECT id, name, description, probability, color FROM wheel_prizes WHERE is_active = 1"
        )
        prizes = await cursor.fetchall()
        
        if not prizes:
            return None
        
        # Выбираем приз по вероятности
        rand = secrets.SystemRandom().random()
        cumulative = 0
        selected = prizes[-1]  # fallback
        
        for prize in prizes:
            cumulative += prize[3]
            if rand <= cumulative:
                selected = prize
                break
        
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")
        await db.execute(
            "INSERT INTO wheel_spins (user_id, spin_date, prize) VALUES (?, ?, ?)",
            (user_id, now, selected[1])
        )
        await db.commit()
        
        return {
            "name": selected[1],
            "description": selected[2],
            "color": selected[4]
        }


async def get_user_stats(user_id: int):
    """Статистика пользователя"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM appointments WHERE user_id = ? AND status = 'confirmed'",
            (user_id,)
        )
        total = await cursor.fetchone()
        
        cursor = await db.execute(
            "SELECT COUNT(*) FROM wheel_spins WHERE user_id = ?",
            (user_id,)
        )
        spins = await cursor.fetchone()
        
        return {"appointments": total[0] if total else 0, "spins": spins[0] if spins else 0}


# ============= ВЕРИФИКАЦИЯ TELEGRAM WEBAPP =============

def verify_telegram_init_data(init_data: str) -> dict | None:
    """
    Верифицировать init_data от Telegram WebApp.
    Возвращает dict с данными пользователя или None.
    """
    from urllib.parse import parse_qs, unquote
    
    try:
        params = {}
        for pair in init_data.split('&'):
            if '=' not in pair:
                continue
            key, value = pair.split('=', 1)
            params[key] = unquote(value)
        
        # Вытаскиваем hash и удаляем его из проверяемых данных
        received_hash = params.pop('hash', None)
        if not received_hash:
            return None
        
        # Сортируем и собираем строку для проверки
        sorted_params = '&'.join(
            f"{k}={v}" for k, v in sorted(params.items())
        )
        
        # Вычисляем HMAC
        secret_key = hmac.new(
            b"WebAppData",
            BOT_TOKEN.encode(),
            hashlib.sha256
        ).digest()
        
        expected_hash = hmac.new(
            secret_key,
            sorted_params.encode(),
            hashlib.sha256
        ).hexdigest()
        
        if not hmac.compare_digest(expected_hash, received_hash):
            return None
        
        # Достаем user из JSON
        user_str = params.get('user', '{}')
        try:
            user_data = json.loads(user_str)
        except json.JSONDecodeError:
            user_data = {}
        
        return user_data
    
    except Exception as e:
        logger.error(f"Init data verification error: {e}")
        return None


def get_telegram_id_from_body(body: dict) -> int | None:
    """
    Извлечь telegram_id из запроса.
    Сначала проверяет init_data (Telegram WebApp).
    Если нет init_data — использует telegram_id из data (для тестирования/резерва).
    """
    init_data = body.get("init_data", "")
    data = body.get("data", {})
    
    if init_data:
        user_data = verify_telegram_init_data(init_data)
        if user_data:
            return user_data.get("id")
        return None
    
    # Fallback: если нет init_data (например при тестировании без WebApp)
    return data.get("telegram_id")


# ============= FASTAPI (Mini App Backend) =============


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield

# ВАЖНО: переменная ДОЛЖНА называться app для Railway
app = FastAPI(lifespan=lifespan)


# Раздаем статику (статику раздаёт nginx/reverse-proxy, но для Railway так)
app.mount("/static", StaticFiles(directory=os.path.join(BASEDIR, "static")), name="static")


@app.get("/")
async def root():
    """Главная страница Mini App"""
    html_path = os.path.join(BASEDIR, "static", "index.html")
    if os.path.exists(html_path):
        with open(html_path, encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h1>Mini App not found</h1>")


@app.get("/api/services")
async def get_services_api():
    """API: список услуг"""
    services = await get_services()
    return {"services": services}


@app.post("/api/book")
async def book_appointment(request: Request):
    """API: запись на услугу"""
    try:
        body = await request.json()
        data = body.get("data", {})
        
        telegram_id = get_telegram_id_from_body(body)
        if not telegram_id:
            raise HTTPException(403, "Ошибка аутентификации")
        
        service_id = data.get("service_id")
        date = data.get("date")
        time_slot = data.get("time")
        
        if not all([service_id, date, time_slot]):
            raise HTTPException(400, "Не все поля заполнены")
        
        user_data = await get_or_create_user(telegram_id)
        
        result = await create_appointment(user_data["id"], service_id, date, time_slot)
        
        if "error" in result:
            raise HTTPException(409, result["error"])
        
        return {"success": True, "message": "Запись подтверждена!"}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Book error: {e}")
        raise HTTPException(500, "Ошибка сервера")


@app.post("/api/can-spin")
async def can_spin_api(request: Request):
    """API: проверить можно ли крутить колесо"""
    try:
        body = await request.json()
        
        telegram_id = get_telegram_id_from_body(body)
        if not telegram_id:
            raise HTTPException(403, "Ошибка аутентификации")
        
        user_data = await get_or_create_user(telegram_id)
        
        can, remaining = await can_spin_wheel(user_data["id"])
        
        return {"can_spin": can, "remaining": remaining}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Can-spin error: {e}")
        raise HTTPException(500, "Ошибка сервера")


@app.post("/api/spin")
async def spin_api(request: Request):
    """API: крутить колесо"""
    try:
        body = await request.json()
        
        telegram_id = get_telegram_id_from_body(body)
        if not telegram_id:
            raise HTTPException(403, "Ошибка аутентификации")
        
        user_data = await get_or_create_user(telegram_id)
        
        can, _ = await can_spin_wheel(user_data["id"])
        if not can:
            raise HTTPException(429, "Подождите 24 часа")
        
        prize = await spin_wheel(user_data["id"])
        
        if not prize:
            raise HTTPException(500, "Призы закончились")
        
        return {"prize": prize}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Spin error: {e}")
        raise HTTPException(500, "Ошибка сервера")


@app.post("/api/user")
async def get_user_info(request: Request):
    """API: информация о пользователе"""
    try:
        body = await request.json()
        
        telegram_id = get_telegram_id_from_body(body)
        if not telegram_id:
            raise HTTPException(403, "Ошибка аутентификации")
        
        user_data = await get_or_create_user(telegram_id)
        
        async with aiosqlite.connect(DB_PATH) as db:
            appointments = await get_user_appointments(user_data["id"])
            stats = await get_user_stats(user_data["id"])
            
            return {"appointments": appointments, "stats": stats}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"User info error: {e}")
        raise HTTPException(500, "Ошибка сервера")


# ============= TELEGRAM БОТ (Aiogram) =============

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Команда /start — приветствие и меню"""
    user = await get_or_create_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.full_name
    )
    
    text = (
        f"👋 Привет, {message.from_user.full_name or 'друг'}!\n\n"
        f"Я бот для записи на массаж. Вот что я умею:\n\n"
        f"📅 <b>Записаться</b> — выбери услугу и удобное время\n"
        f"🎡 <b>Колесо фортуны</b> — крути раз в день и выигрывай призы (в Mini App)\n"
        f"👤 <b>Мои записи</b> — посмотреть активные записи\n\n"
        f"🗂 А ещё есть <b>Mini App</b> с красивым интерфейсом — нажми на кнопку внизу чата!"
    )
    
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📅 Записаться"), KeyboardButton(text="🎡 Колесо фортуны")],
            [KeyboardButton(text="👤 Мои записи")]
        ],
        resize_keyboard=True
    )
    
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


# ============= CALLBACK-ХЕНДЛЕРЫ ЗАПИСИ =============


async def get_available_times(db, date: str):
    """Получить свободное время для даты (с 9:00 до 20:00, шаг 1ч)"""
    cursor = await db.execute(
        "SELECT time FROM appointments WHERE date = ? AND status = 'confirmed'",
        (date,)
    )
    busy_times = {row[0] for row in await cursor.fetchall()}
    
    all_times = [f"{h:02d}:00" for h in range(9, 20)]
    available = [t for t in all_times if t not in busy_times]
    return available


@dp.message(lambda m: m.text == "📅 Записаться")
async def show_services(message: types.Message):
    """Шаг 1: выбрать услугу"""
    services = await get_services()
    
    if not services:
        await message.answer("😔 Услуги временно недоступны")
        return
    
    builder = InlineKeyboardBuilder()
    
    for s in services:
        builder.row(InlineKeyboardButton(
            text=f"{s['name']} — {s['price']}₽ / {s['duration']}мин",
            callback_data=f"svc_{s['id']}"
        ))
    
    await message.answer(
        "📅 <b>Выбери услугу:</b>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )


@dp.callback_query(lambda c: c.data.startswith("svc_"))
async def pick_service(callback: types.CallbackQuery):
    """Шаг 2: выбрать дату"""
    service_id = callback.data.split("_")[1]
    
    today = datetime.now(timezone.utc)
    dates = [
        today.strftime("%Y-%m-%d"),
        (today + timedelta(days=1)).strftime("%Y-%m-%d"),
        (today + timedelta(days=2)).strftime("%Y-%m-%d"),
    ]
    labels = ["Сегодня", "Завтра", "Послезавтра"]
    
    builder = InlineKeyboardBuilder()
    for i, date in enumerate(dates):
        builder.row(InlineKeyboardButton(
            text=labels[i],
            callback_data=f"dt_{service_id}_{date}"
        ))
    
    await callback.message.edit_text(
        "📅 <b>Выбери дату:</b>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("dt_"))
async def pick_date(callback: types.CallbackQuery):
    """Шаг 3: выбрать время"""
    parts = callback.data.split("_")
    service_id = parts[1]
    date = parts[2]
    
    async with aiosqlite.connect(DB_PATH) as db:
        times = await get_available_times(db, date)
    
    if not times:
        await callback.message.edit_text(
            "😔 На этот день нет свободного времени. Выбери другую дату.",
            parse_mode="HTML"
        )
        await callback.answer()
        return
    
    builder = InlineKeyboardBuilder()
    for t in times:
        builder.row(InlineKeyboardButton(
            text=t,
            callback_data=f"tm_{service_id}_{date}_{t}"
        ))
    
    # Кнопка "Назад" к услугам
    builder.row(InlineKeyboardButton(
        text="🔙 К услугам",
        callback_data="back_to_services"
    ))
    
    await callback.message.edit_text(
        f"📅 <b>Выбери время на {date}:</b>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(lambda c: c.data == "back_to_services")
async def back_to_services(callback: types.CallbackQuery):
    """Вернуться к выбору услуги"""
    services = await get_services()
    
    builder = InlineKeyboardBuilder()
    for s in services:
        builder.row(InlineKeyboardButton(
            text=f"{s['name']} — {s['price']}₽ / {s['duration']}мин",
            callback_data=f"svc_{s['id']}"
        ))
    
    await callback.message.edit_text(
        "📅 <b>Выбери услугу:</b>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("tm_"))
async def pick_time(callback: types.CallbackQuery):
    """Шаг 4: подтверждение записи"""
    parts = callback.data.split("_")
    service_id = int(parts[1])
    date = parts[2]
    time_slot = parts[3]
    
    user = await get_or_create_user(
        callback.from_user.id,
        callback.from_user.username,
        callback.from_user.full_name
    )
    
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT id, name, price FROM services WHERE id = ?",
            (service_id,)
        )
        service = await cursor.fetchone()
    
    confirm_text = (
        f"📅 <b>Подтверждение записи</b>\n\n"
        f"<b>Услуга:</b> {service[1]}\n"
        f"<b>Цена:</b> {service[2]}₽\n"
        f"<b>Дата:</b> {date}\n"
        f"<b>Время:</b> {time_slot}\n\n"
        f"Всё верно?"
    )
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"cfrm_{service_id}_{date}_{time_slot}"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="back_to_services")
    )
    
    await callback.message.edit_text(
        confirm_text,
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("cfrm_"))
async def confirm_booking(callback: types.CallbackQuery):
    """Шаг 5: создаём запись"""
    parts = callback.data.split("_")
    service_id = int(parts[1])
    date = parts[2]
    time_slot = parts[3]
    
    user = await get_or_create_user(
        callback.from_user.id,
        callback.from_user.username,
        callback.from_user.full_name
    )
    
    result = await create_appointment(user["id"], service_id, date, time_slot)
    
    if "error" in result:
        await callback.message.edit_text(
            f"😔 {result['error']}",
            parse_mode="HTML"
        )
        await callback.answer()
        return
    
    await callback.message.edit_text(
        "✅ <b>Запись подтверждена!</b>\n\n"
        f"📅 {date} в {time_slot}\n"
        f"🙏 Ждём вас!",
        parse_mode="HTML"
    )
    await callback.answer()


# ============= КОЛЕСО ФОРТУНЫ =============

@dp.message(lambda m: m.text == "🎡 Колесо фортуны")
async def show_wheel(message: types.Message):
    """Колесо фортуны — только через Mini App"""
    await message.answer(
        "🎡 <b>Колесо фортуны!</b>\n\n"
        "Крути и выигрывай скидки и подарки! 🎉\n\n"
        "Открой Mini App через кнопку <b>«🗂 Mini App»</b> внизу чата 👇",
        parse_mode="HTML"
    )


@dp.message(lambda m: m.text == "👤 Мои записи")
async def show_appointments(message: types.Message):
    """Показать записи пользователя"""
    user = await get_or_create_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.full_name
    )
    
    appointments = await get_user_appointments(user["id"])
    
    if not appointments:
        text = "📭 У тебя пока нет записей.\nНажми «📅 Записаться» чтобы выбрать услугу!"
        await message.answer(text, parse_mode="HTML")
        return
    
    text = "👤 <b>Твои записи:</b>\n\n"
    
    for a in appointments:
        status_emoji = "✅" if a["status"] == "confirmed" else "❌"
        text += f"{status_emoji} <b>{a['service']}</b>\n"
        text += f"   📅 {a['date']} в {a['time']}\n"
        text += f"   Статус: {a['status']}\n\n"
    
    await message.answer(text, parse_mode="HTML")


@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    """Команда /admin — для админов"""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Нет доступа")
        return
    
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM appointments WHERE status = 'confirmed'")
        total = await cursor.fetchone()
        
        cursor = await db.execute("SELECT COUNT(*) FROM users")
        users = await cursor.fetchone()
        
        cursor = await db.execute("SELECT COUNT(*) FROM wheel_spins WHERE date(spin_date) = date('now')")
        today_spins = await cursor.fetchone()
    
    text = (
        f"👑 <b>Панель администратора</b>\n\n"
        f"👥 Пользователей: {users[0]}\n"
        f"📅 Всего записей: {total[0]}\n"
        f"🎡 Крутили сегодня: {today_spins[0]}"
    )
    
    await message.answer(text, parse_mode="HTML")


# ============= ЗАПУСК =============

async def main():
    """Запуск бота и API сервера"""
    await init_db()
    logger.info("База данных инициализирована")
    
    # Запускаем FastAPI в отдельной задаче
    logger.info(f"Запуск API на порту {PORT}")
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=PORT,
        log_level="info"
    )
    server = uvicorn.Server(config)
    
    # Запускаем бота и API параллельно
    from asyncio import sleep
    api_task = asyncio.create_task(server.serve())
    
    # Даем API время на запуск
    await sleep(0.5)
    
    await dp.start_polling(bot)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())