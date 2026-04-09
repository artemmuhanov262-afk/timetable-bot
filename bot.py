import logging
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.ext import MessageHandler, filters
import os
import json
import asyncio
from aiohttp import web
import threading

# Импортируем функции из excel_reader
from excel_reader import (
    load_timetable,
    get_all_groups,
    get_week_type,
    get_week_type_name,
    get_pair_time,
    get_week_schedule,
    get_timetable,
    DAYS_RU
)

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация
TOKEN = os.environ.get("BOT_TOKEN","8717718663:AAG_8d1EXC-_ymij-IcbUxneIoGeVqxj080")
PORT = int(os.environ.get("PORT", 8080))

# Файл для хранения данных пользователей
USER_DATA_FILE = "user_data.json"

# Загружаем расписание при старте
try:
    timetable = load_timetable()
    GROUPS = get_all_groups()
    logger.info(f"Загружено расписание для групп: {GROUPS}")
except Exception as e:
    logger.error(f"Ошибка загрузки расписания: {e}")
    GROUPS = []

# Загружаем данные пользователей
def load_user_data():
    if os.path.exists(USER_DATA_FILE):
        try:
            with open(USER_DATA_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_user_data(data):
    try:
        with open(USER_DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Ошибка сохранения: {e}")

# Загружаем сохраненные группы пользователей
user_groups = load_user_data()

def get_day_schedule(group_name, week_type, day_name):
    """Получает расписание на конкретный день"""
    timetable_data = load_timetable()
    
    if group_name not in timetable_data:
        return None
    
    if week_type not in timetable_data[group_name]:
        return {}
    
    if day_name not in timetable_data[group_name][week_type]:
        return {}
    
    return timetable_data[group_name][week_type][day_name]

def format_schedule_for_day(group_name, week_type, day_name):
    """Форматирует расписание на день"""
    schedule = get_day_schedule(group_name, week_type, day_name)
    
    result = []
    result.append(f"📚 *{group_name}*")
    result.append(f"📅 *{day_name}* ({get_week_type_name(week_type)} неделя)")
    result.append("")
    
    has_lessons = False
    
    for pair_num in range(1, 8):
        start_time, end_time = get_pair_time(pair_num)
        
        if schedule and pair_num in schedule:
            has_lessons = True
            data = schedule[pair_num]
            subject = data.get('subject', '')
            teacher = data.get('teacher', '')
            room = data.get('room', '')
            
            result.append(f"*{pair_num} пара* ({start_time}-{end_time})")
            result.append(f"📖 {subject}")
            if teacher:
                result.append(f"👨‍🏫 {teacher}")
            if room:
                result.append(f"📍 {room}")
            result.append("")
        else:
            result.append(f"*{pair_num} пара* ({start_time}-{end_time})")
            result.append(f"📭 Нет пары")
            result.append("")
    
    if not has_lessons:
        result.append("📭 На сегодня пар нет")
    
    return "\n".join(result)

def format_week_schedule(group_name, week_type):
    """Форматирует расписание на всю неделю для указанного типа недели"""
    week_schedule_data = get_week_schedule(group_name, week_type)
    
    if not week_schedule_data:
        return f"❌ Нет данных для группы {group_name} на {get_week_type_name(week_type)} неделе"
    
    result = []
    result.append(f"📅 *Расписание на неделю ({get_week_type_name(week_type)} неделя)*")
    result.append(f"🎓 *Группа: {group_name}*")
    result.append("")
    
    for day_name in DAYS_RU:
        result.append(f"\n*{day_name.upper()}*:")
        
        day_schedule = week_schedule_data.get(day_name, {})
        
        for pair_num in range(1, 8):
            start_time, end_time = get_pair_time(pair_num)
            
            if pair_num in day_schedule:
                data = day_schedule[pair_num]
                subject = data.get('subject', '')
                teacher = data.get('teacher', '')
                room = data.get('room', '')
                
                result.append(f"  *{pair_num} пара* ({start_time}-{end_time})")
                result.append(f"    📖 {subject}")
                if teacher:
                    result.append(f"    👨‍🏫 {teacher}")
                if room:
                    result.append(f"    📍 {room}")
                result.append("")
            else:
                result.append(f"  *{pair_num} пара* ({start_time}-{end_time})")
                result.append(f"    📭 Нет пары")
                result.append("")
    
    return "\n".join(result)

def get_main_keyboard(user_id=None):
    """Создает главную клавиатуру с информацией о группе и неделе"""
    keyboard = [
        [InlineKeyboardButton("📅 Расписание на сегодня", callback_data="today")],
        [InlineKeyboardButton("📆 Расписание на завтра", callback_data="tomorrow")],
        [InlineKeyboardButton("📚 Расписание на неделю", callback_data="week_schedule")],
        [InlineKeyboardButton("🎓 Выбрать группу", callback_data="select_group")],
        [InlineKeyboardButton("ℹ️ Информация", callback_data="info")]
    ]
    
    info_text = ""
    if user_id and user_id in user_groups:
        group_name = user_groups[user_id]
        week_type = get_week_type()
        week_name = get_week_type_name(week_type)
        info_text = f"\n\n👥 *Группа:* {group_name}\n📅 *Неделя:* {week_name}"
    
    return InlineKeyboardMarkup(keyboard), info_text

def get_group_keyboard():
    """Создает клавиатуру с группами"""
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
    """Создает клавиатуру для выбора недели"""
    current_week = get_week_type()
    current_week_name = get_week_type_name(current_week)
    
    keyboard = [
        [InlineKeyboardButton("📗 Над чертой (I неделя)", callback_data=f"week_over_{group_name}")],
        [InlineKeyboardButton("📘 Под чертой (II неделя)", callback_data=f"week_under_{group_name}")],
        [InlineKeyboardButton(f"⭐ Текущая неделя ({current_week_name})", callback_data=f"week_current_{group_name}")],
        [InlineKeyboardButton("🔙 Назад к выбору группы", callback_data="back_to_groups")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(keyboard)

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = str(user.id)
    
    welcome_text = f"""
🎓 *Привет, {user.first_name}!*

Я бот-расписание факультета "Экономика и право".

📚 *Что я умею:*
• Показывать расписание на сегодня/завтра
• Показывать расписание на всю неделю (над чертой/под чертой)
• Сохранять вашу группу

👉 *Нажмите на кнопки ниже, чтобы начать!*
    """
    
    keyboard, info_text = get_main_keyboard(user_id)
    welcome_text += info_text
    
    await update.message.reply_text(
        welcome_text,
        parse_mode='Markdown',
        reply_markup=keyboard
    )

# Команда /help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
📚 *Помощь по командам:*

/start - Главное меню
/help - Эта справка
/today - Расписание на сегодня
/tomorrow - Расписание на завтра
/week - Расписание на неделю (с выбором недели)
/setgroup - Выбрать группу
/mygroup - Показать мою группу

*Как пользоваться:*
1. Нажмите /setgroup или кнопку "Выбрать группу"
2. Выберите свою группу из списка
3. Используйте /today для просмотра расписания

📅 *Недели:*
• Над чертой (I) - верхняя неделя
• Под чертой (II) - нижняя неделя

*Чтобы посмотреть расписание на другую неделю:*
Нажмите "Расписание на неделю" и выберите нужную неделю
    """
    await update.message.reply_text(help_text, parse_mode='Markdown')

# Команда /today
async def today_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    
    if user_id not in user_groups:
        keyboard, info_text = get_main_keyboard(user_id)
        await update.message.reply_text(
            "❌ Вы не выбрали группу!\n\n"
            "Используйте /setgroup или нажмите кнопку 'Выбрать группу'",
            parse_mode='Markdown',
            reply_markup=keyboard
        )
        return
    
    group_name = user_groups[user_id]
    week_type = get_week_type()
    today = datetime.now()
    weekday = today.weekday()
    day_name = DAYS_RU[weekday]
    
    schedule = get_day_schedule(group_name, week_type, day_name)
    
    if not schedule:
        keyboard, info_text = get_main_keyboard(user_id)
        await update.message.reply_text(
            f"📭 *{group_name}*\nСегодня ({day_name}) пар нет! 🎉",
            parse_mode='Markdown',
            reply_markup=keyboard
        )
        return
    
    text = format_schedule_for_day(group_name, week_type, day_name)
    keyboard, info_text = get_main_keyboard(user_id)
    
    await update.message.reply_text(text, parse_mode='Markdown', reply_markup=keyboard)

# Команда /tomorrow
async def tomorrow_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    
    if user_id not in user_groups:
        keyboard, info_text = get_main_keyboard(user_id)
        await update.message.reply_text(
            "❌ Вы не выбрали группу!\n\n"
            "Используйте /setgroup",
            parse_mode='Markdown',
            reply_markup=keyboard
        )
        return
    
    group_name = user_groups[user_id]
    week_type = get_week_type()
    tomorrow = datetime.now() + timedelta(days=1)
    weekday = tomorrow.weekday()
    day_name = DAYS_RU[weekday]
    
    schedule = get_day_schedule(group_name, week_type, day_name)
    
    if not schedule:
        keyboard, info_text = get_main_keyboard(user_id)
        await update.message.reply_text(
            f"📭 *{group_name}*\nЗавтра ({day_name}) пар нет! 🎉",
            parse_mode='Markdown',
            reply_markup=keyboard
        )
        return
    
    text = format_schedule_for_day(group_name, week_type, day_name)
    keyboard, info_text = get_main_keyboard(user_id)
    
    await update.message.reply_text(text, parse_mode='Markdown', reply_markup=keyboard)

# Команда /week
async def week_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    
    if user_id not in user_groups:
        keyboard, info_text = get_main_keyboard(user_id)
        await update.message.reply_text(
            "❌ Вы не выбрали группу!\n\n"
            "Используйте /setgroup",
            parse_mode='Markdown',
            reply_markup=keyboard
        )
        return
    
    group_name = user_groups[user_id]
    await update.message.reply_text(
        f"📚 *Группа {group_name}*\n\nВыберите неделю для просмотра расписания:",
        parse_mode='Markdown',
        reply_markup=get_week_keyboard(group_name)
    )

# Команда /setgroup
async def setgroup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not GROUPS:
        await update.message.reply_text("❌ Список групп не загружен. Попробуйте позже.")
        return
    
    keyboard = get_group_keyboard()
    if keyboard:
        await update.message.reply_text(
            "🎓 *Выберите вашу группу:*",
            parse_mode='Markdown',
            reply_markup=keyboard
        )
    else:
        await update.message.reply_text("❌ Нет доступных групп")

# Команда /mygroup
async def mygroup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    
    if user_id in user_groups:
        group_name = user_groups[user_id]
        week_type = get_week_type()
        week_name = get_week_type_name(week_type)
        keyboard, info_text = get_main_keyboard(user_id)
        await update.message.reply_text(
            f"✅ *Ваша группа:* {group_name}\n📅 *Текущая неделя:* {week_name}",
            parse_mode='Markdown',
            reply_markup=keyboard
        )
    else:
        keyboard, info_text = get_main_keyboard(user_id)
        await update.message.reply_text(
            "❌ Вы не выбрали группу!\n\n"
            "Используйте /setgroup",
            parse_mode='Markdown',
            reply_markup=keyboard
        )

# Обработка callback-запросов
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = str(query.from_user.id)
    
    try:
        await query.answer()
        data = query.data
        
        logger.info(f"Callback data: {data}")
        
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
                "🎓 *Выберите вашу группу:*",
                parse_mode='Markdown',
                reply_markup=get_group_keyboard()
            )
            return
        
        if data == "today":
            if user_id not in user_groups:
                keyboard, info_text = get_main_keyboard(user_id)
                await query.edit_message_text(
                    "❌ Вы не выбрали группу!\n\n"
                    "Нажмите 'Выбрать группу' в главном меню",
                    parse_mode='Markdown',
                    reply_markup=keyboard
                )
                return
            
            group_name = user_groups[user_id]
            week_type = get_week_type()
            today = datetime.now()
            weekday = today.weekday()
            day_name = DAYS_RU[weekday]
            
            schedule = get_day_schedule(group_name, week_type, day_name)
            
            if not schedule:
                text = f"📭 *{group_name}*\nСегодня ({day_name}) пар нет! 🎉"
            else:
                text = format_schedule_for_day(group_name, week_type, day_name)
            
            keyboard, info_text = get_main_keyboard(user_id)
            await query.edit_message_text(
                text,
                parse_mode='Markdown',
                reply_markup=keyboard
            )
            return
        
        if data == "tomorrow":
            if user_id not in user_groups:
                keyboard, info_text = get_main_keyboard(user_id)
                await query.edit_message_text(
                    "❌ Вы не выбрали группу!",
                    parse_mode='Markdown',
                    reply_markup=keyboard
                )
                return
            
            group_name = user_groups[user_id]
            week_type = get_week_type()
            tomorrow = datetime.now() + timedelta(days=1)
            weekday = tomorrow.weekday()
            day_name = DAYS_RU[weekday]
            
            schedule = get_day_schedule(group_name, week_type, day_name)
            
            if not schedule:
                text = f"📭 *{group_name}*\nЗавтра ({day_name}) пар нет! 🎉"
            else:
                text = format_schedule_for_day(group_name, week_type, day_name)
            
            keyboard, info_text = get_main_keyboard(user_id)
            await query.edit_message_text(
                text,
                parse_mode='Markdown',
                reply_markup=keyboard
            )
            return
        
        if data == "week_schedule":
            if user_id not in user_groups:
                keyboard, info_text = get_main_keyboard(user_id)
                await query.edit_message_text(
                    "❌ Вы не выбрали группу!",
                    parse_mode='Markdown',
                    reply_markup=keyboard
                )
                return
            
            group_name = user_groups[user_id]
            await query.edit_message_text(
                f"📚 *Группа {group_name}*\n\nВыберите неделю для просмотра расписания:",
                parse_mode='Markdown',
                reply_markup=get_week_keyboard(group_name)
            )
            return
        
        if data.startswith("week_over_"):
            group_name = data[10:]
            week_type = 1
            text = format_week_schedule(group_name, week_type)
            await query.edit_message_text(
                text,
                parse_mode='Markdown',
                reply_markup=get_week_keyboard(group_name)
            )
            return
        
        if data.startswith("week_under_"):
            group_name = data[11:]
            week_type = 2
            text = format_week_schedule(group_name, week_type)
            await query.edit_message_text(
                text,
                parse_mode='Markdown',
                reply_markup=get_week_keyboard(group_name)
            )
            return
        
        if data.startswith("week_current_"):
            group_name = data[13:]
            week_type = get_week_type()
            text = format_week_schedule(group_name, week_type)
            await query.edit_message_text(
                text,
                parse_mode='Markdown',
                reply_markup=get_week_keyboard(group_name)
            )
            return
        
        if data == "select_group":
            if not GROUPS:
                await query.edit_message_text("❌ Список групп не загружен")
                return
            
            keyboard = get_group_keyboard()
            await query.edit_message_text(
                "🎓 *Выберите вашу группу:*",
                parse_mode='Markdown',
                reply_markup=keyboard
            )
            return
        
        if data == "info":
            info_text = """
ℹ️ *Информация о боте*

🤖 Бот расписания факультета "Экономика и право"

📅 *Недели:*
• Над чертой (I) - верхняя неделя
• Под чертой (II) - нижняя неделя

🕐 *Время пар:*
1 пара: 08:30 - 10:00
2 пара: 10:10 - 11:40
3 пара: 12:20 - 13:50
4 пара: 14:00 - 15:30
5 пара: 15:40 - 17:10
6 пара: 17:20 - 18:50
7 пара: 19:00 - 20:30

📞 По вопросам обращайтесь к администратору.
            """
            keyboard, _ = get_main_keyboard(user_id)
            await query.edit_message_text(
                info_text,
                parse_mode='Markdown',
                reply_markup=keyboard
            )
            return
        
        if data.startswith("group_"):
            group_name = data[6:]
            user_groups[user_id] = group_name
            save_user_data(user_groups)
            
            keyboard, info_text = get_main_keyboard(user_id)
            await query.edit_message_text(
                f"✅ *Группа {group_name} сохранена!*{info_text}\n\n"
                f"Теперь вы можете:\n"
                f"• Нажать 'Расписание на сегодня'\n"
                f"• Или использовать команду /today\n"
                f"• Или посмотреть расписание на неделю",
                parse_mode='Markdown',
                reply_markup=keyboard
            )
            return
        
        await query.edit_message_text(
            "❌ Неизвестная команда",
            reply_markup=get_main_keyboard(user_id)[0]
        )
        
    except Exception as e:
        logger.error(f"Ошибка в callback: {e}")
        try:
            keyboard, info_text = get_main_keyboard(user_id)
            await query.edit_message_text(
                f"❌ Произошла ошибка. Попробуйте позже.{info_text}",
                parse_mode='Markdown',
                reply_markup=keyboard
            )
        except:
            pass

# Веб-сервер для пинга и keep-alive
async def health_check(request):
    return web.Response(text="🤖 Бот работает!", status=200)

async def run_web_server():
    app = web.Application()
    app.router.add_get('/', health_check)
    app.router.add_get('/health', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logger.info(f"🌐 Веб-сервер запущен на порту {PORT}")
    
    # Бесконечное ожидание
    while True:
        await asyncio.sleep(3600)

# Запуск веб-сервера в отдельном потоке
def start_web_server():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run_web_server())

# Главная функция
def main():
    if not TOKEN:
        print("❌ ОШИБКА: Токен бота не указан!")
        return
    
    print("="*50)
    print("🤖 ЗАПУСК БОТА")
    print("="*50)
    print(f"📚 Загружено групп: {len(GROUPS)}")
    print(f"👥 Загружено пользователей: {len(user_groups)}")
    print(f"🌐 Веб-сервер будет на порту: {PORT}")
    print("="*50)
    
    # Запускаем веб-сервер в отдельном потоке
    web_thread = threading.Thread(target=start_web_server, daemon=True)
    web_thread.start()
    
    # Запускаем бота
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("today", today_schedule))
    application.add_handler(CommandHandler("tomorrow", tomorrow_schedule))
    application.add_handler(CommandHandler("week", week_schedule))
    application.add_handler(CommandHandler("setgroup", setgroup))
    application.add_handler(CommandHandler("mygroup", mygroup))
    
    application.add_handler(CallbackQueryHandler(button_callback))
    
    print("✅ Бот запущен и готов к работе!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
