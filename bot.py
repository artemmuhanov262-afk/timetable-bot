import logging
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, AIORateLimiter
import os
import json
from aiohttp import web
import asyncio
import psycopg2
from psycopg2.extras import DictCursor

# Импортируем функции из excel_reader
from excel_reader import (
    load_timetable,
    get_all_groups,
    get_week_type,
    get_week_type_name,
    get_pair_time,
    get_week_schedule,
    DAYS_RU
)

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация - ТОЛЬКО из переменных окружения
TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    raise ValueError("BOT_TOKEN environment variable is not set")

PORT = int(os.environ.get("PORT", 10000))
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
if not WEBHOOK_URL:
    raise ValueError("WEBHOOK_URL environment variable is not set")

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is not set")

# Кеш для расписания
_timetable_cache = None
_timetable_cache_time = None
CACHE_TTL = 300  # 5 минут

def get_cached_timetable():
    """Кешированная загрузка расписания"""
    global _timetable_cache, _timetable_cache_time
    now = datetime.now()
    if (_timetable_cache is None or 
        _timetable_cache_time is None or 
        (now - _timetable_cache_time).seconds > CACHE_TTL):
        try:
            _timetable_cache = load_timetable()
            _timetable_cache_time = now
            logger.info("Timetable reloaded")
        except Exception as e:
            logger.error(f"Error loading timetable: {e}")
            if _timetable_cache is None:
                raise
    return _timetable_cache

# Загружаем список групп
try:
    timetable = get_cached_timetable()
    GROUPS = get_all_groups()
    logger.info(f"Loaded groups: {GROUPS}")
except Exception as e:
    logger.error(f"Error loading groups: {e}")
    GROUPS = []

# Работа с базой данных
def init_database():
    """Инициализация таблиц в PostgreSQL"""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        
        # Создаем таблицу для пользователей
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id VARCHAR(50) PRIMARY KEY,
                group_name VARCHAR(100) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Создаем таблицу для логов (опционально)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bot_logs (
                id SERIAL PRIMARY KEY,
                user_id VARCHAR(50),
                command VARCHAR(50),
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        conn.commit()
        cur.close()
        conn.close()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Database initialization error: {e}")
        raise

def get_user_group(user_id):
    """Получить группу пользователя из базы данных"""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor(cursor_factory=DictCursor)
        cur.execute("SELECT group_name FROM users WHERE user_id = %s", (user_id,))
        result = cur.fetchone()
        cur.close()
        conn.close()
        return result['group_name'] if result else None
    except Exception as e:
        logger.error(f"Error getting user group: {e}")
        return None

def set_user_group(user_id, group_name):
    """Сохранить группу пользователя в базу данных"""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO users (user_id, group_name, updated_at) 
            VALUES (%s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (user_id) 
            DO UPDATE SET group_name = %s, updated_at = CURRENT_TIMESTAMP
        """, (user_id, group_name, group_name))
        conn.commit()
        cur.close()
        conn.close()
        logger.info(f"Saved group {group_name} for user {user_id}")
        return True
    except Exception as e:
        logger.error(f"Error saving user group: {e}")
        return False

def get_all_users():
    """Получить всех пользователей (для администрирования)"""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor(cursor_factory=DictCursor)
        cur.execute("SELECT user_id, group_name, created_at, updated_at FROM users ORDER BY updated_at DESC")
        results = cur.fetchall()
        cur.close()
        conn.close()
        return [dict(row) for row in results]
    except Exception as e:
        logger.error(f"Error getting all users: {e}")
        return []

def log_command(user_id, command):
    """Логирование команд пользователей"""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO bot_logs (user_id, command) VALUES (%s, %s)",
            (user_id, command)
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"Error logging command: {e}")

# Инициализируем базу данных при старте
init_database()

def get_day_schedule(group_name, week_type, day_name):
    """Получение расписания на день"""
    timetable_data = get_cached_timetable()
    if group_name not in timetable_data:
        return None
    if week_type not in timetable_data[group_name]:
        return {}
    if day_name not in timetable_data[group_name][week_type]:
        return {}
    return timetable_data[group_name][week_type][day_name]

def format_schedule_for_day(group_name, week_type, day_name):
    """Форматирование расписания на день"""
    schedule = get_day_schedule(group_name, week_type, day_name)
    result = [f"📚 *{group_name}*", f"📅 *{day_name}* ({get_week_type_name(week_type)} неделя)", ""]
    has_lessons = False
    
    for pair_num in range(1, 8):
        start_time, end_time = get_pair_time(pair_num)
        if schedule and pair_num in schedule:
            has_lessons = True
            data = schedule[pair_num]
            result.append(f"*{pair_num} пара* ({start_time}-{end_time})")
            result.append(f"📖 {data.get('subject', '')}")
            if data.get('teacher'):
                result.append(f"👨‍🏫 {data['teacher']}")
            if data.get('room'):
                result.append(f"📍 {data['room']}")
            result.append("")
        else:
            result.append(f"*{pair_num} пара* ({start_time}-{end_time})")
            result.append("📭 Нет пары\n")
    
    if not has_lessons:
        result.append("📭 На сегодня пар нет")
    
    return "\n".join(result)

def format_week_schedule(group_name, week_type):
    """Форматирование расписания на неделю"""
    week_schedule_data = get_week_schedule(group_name, week_type)
    if not week_schedule_data:
        return f"❌ Нет данных для группы {group_name} на {get_week_type_name(week_type)} неделе"
    
    result = [f"📅 *Расписание на неделю ({get_week_type_name(week_type)} неделя)*", f"🎓 *Группа: {group_name}*", ""]
    
    for day_name in DAYS_RU:
        result.append(f"\n*{day_name.upper()}*:")
        day_schedule = week_schedule_data.get(day_name, {})
        day_has_lessons = False
        
        for pair_num in range(1, 8):
            start_time, end_time = get_pair_time(pair_num)
            if pair_num in day_schedule:
                day_has_lessons = True
                data = day_schedule[pair_num]
                result.append(f"  *{pair_num} пара* ({start_time}-{end_time})")
                result.append(f"    📖 {data.get('subject', '')}")
                if data.get('teacher'):
                    result.append(f"    👨‍🏫 {data['teacher']}")
                if data.get('room'):
                    result.append(f"    📍 {data['room']}")
                result.append("")
            else:
                result.append(f"  *{pair_num} пара* ({start_time}-{end_time})")
                result.append("    📭 Нет пары\n")
        
        if not day_has_lessons:
            result.append("  📭 Пар нет\n")
    
    return "\n".join(result)

def get_main_keyboard(user_id=None):
    """Главная клавиатура"""
    keyboard = [
        [InlineKeyboardButton("📅 Расписание на сегодня", callback_data="today")],
        [InlineKeyboardButton("📆 Расписание на завтра", callback_data="tomorrow")],
        [InlineKeyboardButton("📚 Расписание на неделю", callback_data="week_schedule")],
        [InlineKeyboardButton("🎓 Выбрать группу", callback_data="select_group")],
        [InlineKeyboardButton("ℹ️ Информация", callback_data="info")]
    ]
    
    info_text = ""
    if user_id:
        group_name = get_user_group(user_id)
        if group_name:
            week_name = get_week_type_name(get_week_type())
            info_text = f"\n\n👥 *Группа:* {group_name}\n📅 *Неделя:* {week_name}"
    
    return InlineKeyboardMarkup(keyboard), info_text

def get_group_keyboard():
    """Клавиатура выбора группы"""
    if not GROUPS:
        return None
    
    keyboard = []
    row = []
    for i, group in enumerate(GROUPS):
        row.append(InlineKeyboardButton(group, callback_data=f"group_{group}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton("🏠 Главное меню", callback_data="back_to_main")])
    return InlineKeyboardMarkup(keyboard)

def get_week_keyboard(group_name):
    """Клавиатура выбора недели"""
    current_week_name = get_week_type_name(get_week_type())
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📗 Над чертой (I неделя)", callback_data=f"week_over_{group_name}")],
        [InlineKeyboardButton("📘 Под чертой (II неделя)", callback_data=f"week_under_{group_name}")],
        [InlineKeyboardButton(f"⭐ Текущая неделя ({current_week_name})", callback_data=f"week_current_{group_name}")],
        [InlineKeyboardButton("🔙 Назад к выбору группы", callback_data="back_to_groups")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="back_to_main")]
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user = update.effective_user
    user_id = str(user.id)
    keyboard, info_text = get_main_keyboard(user_id)
    
    await update.message.reply_text(
        f"🎓 *Привет, {user.first_name}!*\n\n"
        f"Я бот-расписание факультета 'Экономика и право'.\n\n"
        f"👉 *Нажмите на кнопки ниже!*{info_text}",
        parse_mode='Markdown',
        reply_markup=keyboard
    )
    
    # Логируем команду
    log_command(user_id, "start")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /help"""
    user_id = str(update.effective_user.id)
    await update.message.reply_text(
        "📚 *Помощь:*\n"
        "/today - расписание на сегодня\n"
        "/tomorrow - на завтра\n"
        "/week - на неделю\n"
        "/setgroup - выбрать группу\n"
        "/mygroup - показать мою группу",
        parse_mode='Markdown'
    )
    log_command(user_id, "help")

async def today_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать расписание на сегодня"""
    user_id = str(update.effective_user.id)
    log_command(user_id, "today")
    
    group_name = get_user_group(user_id)
    if not group_name:
        keyboard, _ = get_main_keyboard(user_id)
        await update.message.reply_text(
            "❌ Выберите группу через /setgroup",
            reply_markup=keyboard
        )
        return
    
    week_type = get_week_type()
    day_name = DAYS_RU[datetime.now().weekday()]
    schedule = get_day_schedule(group_name, week_type, day_name)
    
    if not schedule:
        await update.message.reply_text(
            f"📭 *{group_name}*\nСегодня ({day_name}) пар нет! 🎉",
            parse_mode='Markdown'
        )
        return
    
    text = format_schedule_for_day(group_name, week_type, day_name)
    keyboard, _ = get_main_keyboard(user_id)
    
    # Разбиваем длинные сообщения
    if len(text) > 4096:
        for i in range(0, len(text), 4096):
            await update.message.reply_text(
                text[i:i+4096],
                parse_mode='Markdown',
                reply_markup=keyboard if i == 0 else None
            )
    else:
        await update.message.reply_text(text, parse_mode='Markdown', reply_markup=keyboard)

async def tomorrow_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать расписание на завтра"""
    user_id = str(update.effective_user.id)
    log_command(user_id, "tomorrow")
    
    group_name = get_user_group(user_id)
    if not group_name:
        keyboard, _ = get_main_keyboard(user_id)
        await update.message.reply_text(
            "❌ Выберите группу через /setgroup",
            reply_markup=keyboard
        )
        return
    
    week_type = get_week_type()
    day_name = DAYS_RU[(datetime.now() + timedelta(days=1)).weekday()]
    schedule = get_day_schedule(group_name, week_type, day_name)
    
    if not schedule:
        await update.message.reply_text(
            f"📭 *{group_name}*\nЗавтра ({day_name}) пар нет! 🎉",
            parse_mode='Markdown'
        )
        return
    
    text = format_schedule_for_day(group_name, week_type, day_name)
    keyboard, _ = get_main_keyboard(user_id)
    await update.message.reply_text(text, parse_mode='Markdown', reply_markup=keyboard)

async def week_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать расписание на неделю"""
    user_id = str(update.effective_user.id)
    log_command(user_id, "week")
    
    group_name = get_user_group(user_id)
    if not group_name:
        await update.message.reply_text("❌ Выберите группу через /setgroup")
        return
    
    await update.message.reply_text(
        f"📚 *Группа {group_name}*\n\nВыберите неделю:",
        parse_mode='Markdown',
        reply_markup=get_week_keyboard(group_name)
    )

async def setgroup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбрать группу"""
    user_id = str(update.effective_user.id)
    log_command(user_id, "setgroup")
    
    if not GROUPS:
        await update.message.reply_text("❌ Список групп не загружен")
        return
    
    await update.message.reply_text(
        "🎓 *Выберите группу:*",
        parse_mode='Markdown',
        reply_markup=get_group_keyboard()
    )

async def mygroup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать выбранную группу"""
    user_id = str(update.effective_user.id)
    log_command(user_id, "mygroup")
    
    group_name = get_user_group(user_id)
    if group_name:
        await update.message.reply_text(
            f"✅ Ваша группа: *{group_name}*",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text("❌ Группа не выбрана. Используйте /setgroup")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик нажатий на кнопки"""
    query = update.callback_query
    user_id = str(query.from_user.id)
    await query.answer()
    data = query.data
    
    # Логируем действие
    log_command(user_id, f"callback_{data[:50]}")
    
    # Обработка навигации
    if data == "back_to_main":
        keyboard, info_text = get_main_keyboard(user_id)
        await query.edit_message_text(
            f"🎓 *Главное меню*{info_text}",
            parse_mode='Markdown',
            reply_markup=keyboard
        )
        return
    
    if data == "back_to_groups":
        await query.edit_message_text(
            "🎓 *Выберите группу:*",
            parse_mode='Markdown',
            reply_markup=get_group_keyboard()
        )
        return
    
    # Обработка сегодня/завтра
    if data == "today":
        group_name = get_user_group(user_id)
        if not group_name:
            await query.edit_message_text("❌ Выберите группу в главном меню")
            return
        
        week_type = get_week_type()
        day_name = DAYS_RU[datetime.now().weekday()]
        schedule = get_day_schedule(group_name, week_type, day_name)
        
        if schedule:
            text = format_schedule_for_day(group_name, week_type, day_name)
        else:
            text = f"📭 *{group_name}*\nСегодня ({day_name}) пар нет! 🎉"
        
        keyboard, _ = get_main_keyboard(user_id)
        await query.edit_message_text(
            text,
            parse_mode='Markdown',
            reply_markup=keyboard
        )
        return
    
    if data == "tomorrow":
        group_name = get_user_group(user_id)
        if not group_name:
            await query.edit_message_text("❌ Выберите группу в главном меню")
            return
        
        week_type = get_week_type()
        day_name = DAYS_RU[(datetime.now() + timedelta(days=1)).weekday()]
        schedule = get_day_schedule(group_name, week_type, day_name)
        
        if schedule:
            text = format_schedule_for_day(group_name, week_type, day_name)
        else:
            text = f"📭 *{group_name}*\nЗавтра ({day_name}) пар нет! 🎉"
        
        keyboard, _ = get_main_keyboard(user_id)
        await query.edit_message_text(
            text,
            parse_mode='Markdown',
            reply_markup=keyboard
        )
        return
    
    # Обработка недельного расписания
    if data == "week_schedule":
        group_name = get_user_group(user_id)
        if not group_name:
            await query.edit_message_text("❌ Выберите группу в главном меню")
            return
        
        await query.edit_message_text(
            f"📚 *Группа {group_name}*\n\nВыберите неделю:",
            parse_mode='Markdown',
            reply_markup=get_week_keyboard(group_name)
        )
        return
    
    if data.startswith("week_over_"):
        group_name = data[10:]
        text = format_week_schedule(group_name, 1)
        await query.edit_message_text(
            text,
            parse_mode='Markdown',
            reply_markup=get_week_keyboard(group_name)
        )
        return
    
    if data.startswith("week_under_"):
        group_name = data[11:]
        text = format_week_schedule(group_name, 2)
        await query.edit_message_text(
            text,
            parse_mode='Markdown',
            reply_markup=get_week_keyboard(group_name)
        )
        return
    
    if data.startswith("week_current_"):
        group_name = data[13:]
        text = format_week_schedule(group_name, get_week_type())
        await query.edit_message_text(
            text,
            parse_mode='Markdown',
            reply_markup=get_week_keyboard(group_name)
        )
        return
    
    # Обработка выбора группы
    if data == "select_group":
        await query.edit_message_text(
            "🎓 *Выберите группу:*",
            parse_mode='Markdown',
            reply_markup=get_group_keyboard()
        )
        return
    
    if data == "info":
        keyboard, info_text = get_main_keyboard(user_id)
        await query.edit_message_text(
            "ℹ️ *Информация о боте*\n\n"
            "🤖 Бот расписания факультета \"Экономика и право\"\n\n"
            "📅 *Недели:*\n"
            "• Над чертой (I) - верхняя неделя\n"
            "• Под чертой (II) - нижняя неделя\n\n"
            "🕐 *Время пар:*\n"
            "1 пара: 08:30 - 10:00\n"
            "2 пара: 10:10 - 11:40\n"
            "3 пара: 12:20 - 13:50\n"
            "4 пара: 14:00 - 15:30\n"
            "5 пара: 15:40 - 17:10\n"
            "6 пара: 17:20 - 18:50\n"
            "7 пара: 19:00 - 20:30",
            parse_mode='Markdown',
            reply_markup=keyboard
        )
        return
    
    if data.startswith("group_"):
        group_name = data[6:]
        if set_user_group(user_id, group_name):
            keyboard, info_text = get_main_keyboard(user_id)
            await query.edit_message_text(
                f"✅ *Группа {group_name} сохранена!*{info_text}",
                parse_mode='Markdown',
                reply_markup=keyboard
            )
        else:
            await query.edit_message_text(
                "❌ Ошибка при сохранении группы. Попробуйте позже.",
                parse_mode='Markdown'
            )
        return

# Веб-сервер для Render.com
async def health_check(request):
    """Health check endpoint for Render"""
    # Проверяем соединение с базой данных
    try:
        conn = psycopg2.connect(DATABASE_URL)
        conn.close()
        return web.Response(text="OK", status=200)
    except:
        return web.Response(text="Database Error", status=500)

async def keep_alive():
    """Keep bot awake by pinging itself every 10 minutes"""
    while True:
        await asyncio.sleep(600)  # 10 минут
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{WEBHOOK_URL}/health") as resp:
                    if resp.status == 200:
                        logger.info("Keep-alive ping sent successfully")
                    else:
                        logger.warning(f"Keep-alive ping failed with status: {resp.status}")
        except Exception as e:
            logger.error(f"Keep-alive error: {e}")

async def main():
    """Основная функция запуска бота - ТОЛЬКО WEBHOOK, без polling"""
    logger.info("Starting bot with webhook on Render...")
    logger.info(f"Webhook URL: {WEBHOOK_URL}")
    
    # Проверяем подключение к базе данных
    try:
        conn = psycopg2.connect(DATABASE_URL)
        conn.close()
        logger.info("Database connection successful")
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        raise
    
    # Сначала удаляем все существующие вебхуки, чтобы избежать конфликтов
    temp_app = Application.builder().token(TOKEN).build()
    await temp_app.initialize()
    await temp_app.bot.delete_webhook(drop_pending_updates=True)
    logger.info("Deleted existing webhooks")
    await temp_app.shutdown()
    
    # Создаём приложение бота с параллельной обработкой и ограничителем скорости
    application = Application.builder() \
        .token(TOKEN) \
        .concurrent_updates(10) \
        .rate_limiter(AIORateLimiter()) \
        .build()
    
    # Добавляем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("today", today_schedule))
    application.add_handler(CommandHandler("tomorrow", tomorrow_schedule))
    application.add_handler(CommandHandler("week", week_schedule))
    application.add_handler(CommandHandler("setgroup", setgroup))
    application.add_handler(CommandHandler("mygroup", mygroup))
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # Инициализируем приложение
    await application.initialize()
    
    # Запускаем keep-alive задачу
    asyncio.create_task(keep_alive())
    logger.info("Keep-alive task started")
    
    # Настройка веб-сервера для вебхуков
    app = web.Application()
    
    # Эндпоинт для вебхуков Telegram
    async def webhook(request):
        """Handle incoming Telegram updates"""
        try:
            data = await request.json()
            update = Update.de_json(data, application.bot)
            await application.process_update(update)
            return web.Response(status=200)
        except Exception as e:
            logger.error(f"Webhook error: {e}")
            return web.Response(status=500)
    
    # Регистрируем маршруты
    app.router.add_post(f'/{TOKEN}', webhook)
    app.router.add_get('/', health_check)
    app.router.add_get('/health', health_check)
    
    # Запускаем веб-сервер
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    
    # Устанавливаем вебхук
    webhook_url = f"{WEBHOOK_URL}/{TOKEN}"
    await application.bot.set_webhook(webhook_url)
    logger.info(f"Webhook successfully set to {webhook_url}")
    
    # Запускаем application
    await application.start()
    
    logger.info(f"Bot is running on port {PORT} with webhook! (concurrent_updates=10, rate_limiter=ON)")
    
    # Держим приложение запущенным
    try:
        # Бесконечное ожидание
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        await application.bot.delete_webhook()
        await runner.cleanup()
        await application.stop()
        await application.shutdown()
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        await application.bot.delete_webhook()
        await runner.cleanup()
        await application.stop()
        await application.shutdown()
        raise

if __name__ == "__main__":
    asyncio.run(main())
