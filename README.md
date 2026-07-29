# 🤖 Telegram Bot + Mini App для массажиста

**Бот для записи клиентов с красивым Mini App и колесом фортуны внутри Telegram.**

## 📁 Файлы проекта

| Файл | Что делает |
|------|-----------|
| `bot.py` | **Всё в одном:** бот (aiogram 3), API (FastAPI), SQLite |
| `static/index.html` | Mini App: красивая запись и колесо фортуны |
| `requirements.txt` | Список Python-пакетов для установки |
| `bot.db` | Создастся автоматически при первом запуске |

## 🚀 Быстрый запуск

### 🔹 Вариант 1: Railway (рекомендуется)

Самый простой способ — деплой на Railway одной кнопкой или через CLI.

1. **Создать аккаунт** на [railway.app](https://railway.app/) (через GitHub)
2. **Создать новый проект** → Deploy from GitHub repo
3. **Добавить переменные окружения** в Railway:
   - `BOT_TOKEN` — токен от [@BotFather](https://t.me/BotFather)
   - `WEBAPP_URL` — URL твоего Railway проекта (например `https://bot-tg.up.railway.app`)
   - `SECRET_KEY` — любая случайная строка (например `openssl rand -hex 32`)
   - `ADMIN_IDS` — твой Telegram ID (узнать у [@userinfobot](https://t.me/userinfobot))
4. Railway сам установит `requirements.txt` и запустит `python bot.py`

После деплоя:
- API будет доступен по адресу: `https://твой-проект.up.railway.app/`
- Mini App: `https://твой-проект.up.railway.app/static/`

### 🔹 Вариант 2: Локальный запуск (разработка)

```bash
# 1. Клонировать и зайти в папку
git clone <ссылка_на_репозиторий> && cd bot-tg

# 2. Виртуальное окружение
python -m venv venv
source venv/bin/activate

# 3. Установить пакеты
pip install -r requirements.txt

# 4. Создать .env файл
cp .env.example .env    # или создать вручную
```

Редактируем `.env`:
```
BOT_TOKEN=токен_бота_от_BotFather
WEBAPP_URL=http://localhost:8000
SECRET_KEY=любая_случайная_строка
ADMIN_IDS=твой_telegram_id
```

```bash
# 5. Запуск
python bot.py
```

Бот запустится на **http://localhost:8000**.  
Mini App: **http://localhost:8000/static/**

### 🔹 Вариант 3: Запустить на VPS

```bash
# Закинуть файлы на сервер, установить зависимости
pip install -r requirements.txt

# Экспортировать переменные
export BOT_TOKEN="..."
export WEBAPP_URL="https://твой-домен.ru"
export SECRET_KEY="..."
export ADMIN_IDS="..."

# Установить screen/tmux и запустить
screen -S bot python bot.py
```

### ⚙️ Настройка Mini App в BotFather

После того как сервер запущен:

1. Зайти в [@BotFather](https://t.me/BotFather)
2. Команда: `/mybots` → выбрать бота
3. `Bot Settings` → `Menu Button`
4. Указать URL: `https://твой-домен.ru/static/`

**Важно:** Mini App обязательно должен работать по **HTTPS** (кроме localhost).  
Railway даёт HTTPS автоматически.

## 🎡 Колесо фортуны — безопасность

- Приз **выбирается на сервере** (Python), клиент просто крутит анимацию
- **Лимит 24 часа** проверяется на сервере по UTC
- Все запросы от Mini App к API подписываются **HMAC-SHA256**
- Клиентский JavaScript не может подделать результат — он только показывает анимацию

## 📋 Команды бота

| Команда | Описание |
|---------|----------|
| `/start` | Главное меню с кнопками |
| `/admin` | Статистика (только для админов) |

Кнопки в боте: **📅 Записаться**, **🎡 Колесо фортуны**, **👤 Мои записи**

## 🗄️ База данных (SQLite)

Таблицы создаются автоматически при первом запуске:
- `users` — пользователи Telegram
- `services` — услуги (заполняются тестовыми данными)
- `appointments` — записи клиентов
- `wheel_spins` — история вращений колеса
- `wheel_prizes` — призы с вероятностями

## 🔧 Настройка через переменные окружения

| Переменная | Описание | По умолчанию |
|-----------|----------|-------------|
| `BOT_TOKEN` | Токен бота от @BotFather | `ВАШ_ТОКЕН_БОТА` |
| `WEBAPP_URL` | Публичный URL сервера | `https://ваш-домен.ru` |
| `SECRET_KEY` | Ключ для HMAC подписи | задать свой! |
| `ADMIN_IDS` | Telegram ID админов | `0` |

## 🎨 Дизайн Mini App

Стеклянный (Glassmorphism) дизайн:
- Градиентный фон
- Прозрачные карточки с размытием
- Плавные анимации
- Адаптация под телефон
- Современный, минималистичный стиль

## ❓ Если что-то не работает

1. Проверьте что `BOT_TOKEN` правильный
2. Убедитесь что `WEBAPP_URL` доступен из интернета (или используйте localhost для теста)
3. Порт 8000 не занят другим процессом
4. При ошибке HMAC — проверьте что `SECRET_KEY` одинаковый в `bot.py` и ожидается клиентом