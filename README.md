# 🤖 Telegram Bot + Mini App для массажиста

**Бот для записи клиентов с красивым Mini App и колесом фортуны внутри Telegram.**

## 📁 Файлы проекта

| Файл | Что делает |
|------|-----------|
| `main.py` | **Всё в одном:** бот (aiogram 3), API (FastAPI), SQLite |
| `static/index.html` | Mini App: красивая запись и колесо фортуны |
| `requirements.txt` | Список Python-пакетов для установки |
| `Procfile` | Для деплоя на Railway |
| `.env.example` | Пример переменных окружения |
| `bot.db` | Создастся автоматически при первом запуске |

## 🚀 Быстрый запуск (Railway — рекомендуется)

1. **Создать аккаунт** на [railway.app](https://railway.app/) (через GitHub)
2. **Создать новый проект** → Deploy from GitHub repo
3. **Добавить переменные окружения** в Railway:
   - `BOT_TOKEN` — токен от [@BotFather](https://t.me/BotFather)
   - `WEBAPP_URL` — URL твоего Railway проекта (например `https://bot-tg.up.railway.app`)
   - `SECRET_KEY` — любая случайная строка (например `openssl rand -hex 32`)
   - `ADMIN_IDS` — твой Telegram ID (узнать у [@userinfobot](https://t.me/userinfobot))
4. Railway сам установит `requirements.txt` и запустит `python main.py`
5. После деплоя: `https://твой-проект.up.railway.app/` — Mini App работает

### ⚙️ Настройка Mini App в BotFather

После деплоя:

1. Зайти в [@BotFather](https://t.me/BotFather)
2. `/mybots` → выбрать бота → **Bot Settings** → **Domain**
3. Ввести: `твой-проект.up.railway.app` (без https://)
4. **Bot Settings** → **Menu Button** → **Edit menu button URL**:
   - URL: `https://твой-проект.up.railway.app/`
   - Title: `📅 Записаться на массаж`

## 📋 Как это работает

### Запись через бота (в чате)
1. Нажми `📅 Записаться`
2. Выбери услугу из списка
3. Выбери дату (сегодня/завтра/послезавтра)
4. Выбери свободное время
5. Подтверди запись

### Mini App (через кнопку внизу чата)
- Красивый интерфейс с теми же функциями
- Колесо фортуны (раз в 24 часа)
- Просмотр и управление записями

### Колесо фортуны
- Только в Mini App (через кнопку `🗂 Mini App` внизу)
- Приз выбирается на сервере — накрутить невозможно
- Крутить можно раз в 24 часа

## 🗄️ База данных (SQLite)

Таблицы создаются автоматически при первом запуске:
- `users` — пользователи Telegram
- `services` — услуги (заполняются тестовыми данными)
- `appointments` — записи клиентов
- `wheel_spins` — история вращений колеса
- `wheel_prizes` — призы с вероятностями

## 🔧 Переменные окружения

| Переменная | Описание | По умолчанию |
|-----------|----------|-------------|
| `BOT_TOKEN` | Токен бота от @BotFather | `ВАШ_ТОКЕН_БОТА` |
| `WEBAPP_URL` | Публичный URL сервера | `https://bot-tg-production-f2f4.up.railway.app` |
| `SECRET_KEY` | Ключ для HMAC подписи | задать свой! |
| `ADMIN_IDS` | Telegram ID админов | `0` |

## ❓ Если что-то не работает

1. Проверь что `BOT_TOKEN` правильный
2. Убедись что `WEBAPP_URL` доступен из интернета
3. Порт 8000 не занят другим процессом
4. В BotFather обязательно настроен **Domain** (без https://)