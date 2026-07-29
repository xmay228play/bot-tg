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
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://ваш-домен.ru")  # URL где будет Mini App
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "0").split(",")))  # ID админов через запятую

DB_PATH = "bot.db"

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

# Порт для Railway (они задают PORT, по умолчанию 8000)
PORT = int(os.getenv("PORT", "8000"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield

api = FastAPI(lifespan=lifespan)


@api.get("/")
async def root():
    """Health check для Railway"""
    return {"status": "ok", "app": "Массажный салон"}


# Раздаем статику (фронтенд)
api.mount("/static", StaticFiles(directory="static"), name="static")


@api.get("/api/services")
async def get_services_api():
    """API: список услуг"""
    services = await get_services()
    return {"services": services}


@api.post("/api/book")
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


@api.post("/api/can-spin")
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


@api.post("/api/spin")
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


@api.post("/api/user")
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
        f"🎡 <b>Колесо фортуны</b> — крути раз в день и выигрывай призы\n"
        f"👤 <b>Мои записи</b> — посмотреть активные записи"
    )
    
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📅 Записаться"), KeyboardButton(text="🎡 Колесо фортуны")],
            [KeyboardButton(text="👤 Мои записи")]
        ],
        resize_keyboard=True
    )
    
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


@dp.message(lambda m: m.text == "📅 Записаться")
async def show_services(message: types.Message):
    """Показать список услуг"""
    services = await get_services()
    
    if not services:
        await message.answer("😔 Услуги временно недоступны")
        return
    
    builder = InlineKeyboardBuilder()
    
    for s in services:
        btn_text = f"{s['name']} — {s['price']}₽ / {s['duration']}мин"
        # Кнопка открывает Mini App с выбранной услугой
        webapp_url = f"{WEBAPP_URL}/static/?action=book&service_id={s['id']}&tg_id={message.from_user.id}"
        builder.row(InlineKeyboardButton(
            text=btn_text,
            web_app=WebAppInfo(url=webapp_url)
        ))
    
    await message.answer(
        "📅 <b>Выбери услугу:</b>\n\n"
        "После выбора ты сможешь посмотреть свободные даты и записаться.",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )


@dp.message(lambda m: m.text == "🎡 Колесо фортуны")
async def show_wheel(message: types.Message):
    """Открыть колесо фортуны в Mini App"""
    user = await get_or_create_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.full_name
    )
    
    webapp_url = f"{WEBAPP_URL}/static/?action=wheel&tg_id={message.from_user.id}"
    
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text="🎡 Крутить колесо!",
                web_app=WebAppInfo(url=webapp_url)
            )
        ]]
    )
    
    await message.answer(
        "🎡 <b>Колесо фортуны!</b>\n\n"
        "Крути каждый день и выигрывай скидки и подарки!\n"
        "Каждый день — новый шанс!",
        reply_markup=kb,
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
        api,
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
