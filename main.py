import json
import pytz
import aiohttp
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Update, ReplyKeyboardMarkup, InputFile
from telegram.constants import ChatAction
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

# Константы
TOKEN = '7595932493:AAG7hrJckODArPCX8I2ZZyPj-602xqRPS2c'
API_KEY = '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'
API_URL = 'https://openrouter.ai/api/v1/chat/completions'
MODELS = ['deepseek/deepseek-chat', 'deepseek/deepseek-r1']
current_model = MODELS[0]

# Лимиты
MAX_TOKENS_PER_DAY = 1000  # 10 000 токенов в день

# БД в JSON
DB_FILE = "database.json"

# Админ ID (для тестирования замените на ваш ID)
ADMIN_USER_ID = 5387020491


def load_db():
    """Загрузка данных из JSON-файла"""
    try:
        with open(DB_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_db(data):
    """Сохранение данных в JSON-файл"""
    with open(DB_FILE, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=4)


# Загрузка БД
db = load_db()


async def chat_with_model(user_id, messages):
    """Отправка запроса к AI и списание токенов"""
    global db
    if db[user_id]["tokens"] <= 0:
        return "❌ У вас закончились токены на сегодня. Попробуйте завтра!"

    async with aiohttp.ClientSession() as session:
        async with session.post(
                API_URL,
                headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": current_model,
                    "messages": messages[-5:],  # Ограничиваем историю
                    "max_tokens": min(db[user_id]["tokens"], 150),  # Не больше оставшихся
                    "temperature": 0.6,
                }
        ) as response:
            if response.status != 200:
                return "Ошибка API. Попробуйте позже."
            result = await response.json()
            answer = result.get("choices", [{}])[0].get("message", {}).get("content", "Нет ответа.")

            # Списываем токены (ориентировочно 1 символ = 1 токен)
            tokens_used = len(answer.split()) * 1.5
            db[user_id]["tokens"] -= int(tokens_used)
            save_db(db)

            return answer


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Стартовое сообщение"""
    user_id = str(update.effective_chat.id)

    if user_id not in db:
        db[user_id] = {"tokens": MAX_TOKENS_PER_DAY}
        save_db(db)

    keyboard = [
        ["💬 Новый вопрос", "📊 Остаток токенов"],
        ["🔄 Сменить модель", "🆘 Помощь"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    await update.message.reply_text("👋 Привет! Я DeepSeek AI бот. Чем помочь?", reply_markup=reply_markup)


async def show_tokens(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать оставшиеся токены"""
    user_id = str(update.effective_chat.id)
    tokens_left = db.get(user_id, {}).get("tokens", MAX_TOKENS_PER_DAY)
    await update.message.reply_text(f"📊 У вас осталось {tokens_left} токенов на сегодня.")


async def switch_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Переключение модели"""
    global current_model
    current_model = MODELS[1] if current_model == MODELS[0] else MODELS[0]
    await update.message.reply_text(f"🔄 Теперь используется модель: {current_model}")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка сообщений"""
    user_id = str(update.effective_chat.id)
    user_message = update.message.text

    # Проверяем токены
    if db[user_id]["tokens"] <= 0:
        await update.message.reply_text("❌ У вас закончились токены на сегодня. Попробуйте завтра!")
        return

    # Отправляем действие "печатает..."
    asyncio.create_task(context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING))

    # Запрос к AI
    response = await chat_with_model(user_id, [{"role": "user", "content": user_message}])

    await update.message.reply_text(response)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Справка"""
    await update.message.reply_text(
        "📌 Команды:\n"
        "💬 Просто напишите сообщение — и я отвечу\n"
        "📊 /tokens — Узнать, сколько токенов осталось\n"
        "🔄 /mode — Сменить модель\n"
        "🆘 /help — Показать справку\n"
        "⚙️ /admin — Админ-меню (только для администраторов)"
    )


async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ответ на неизвестные команды"""
    await update.message.reply_text("❌ Неизвестная команда. Используйте /help.")


async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Админ-меню для выгрузки базы данных"""
    user_id = update.effective_chat.id

    if user_id != ADMIN_USER_ID:
        await update.message.reply_text("❌ У вас нет доступа к админ-меню.")
        return

    # Отправляем БД как файл
    with open(DB_FILE, 'rb') as file:
        await update.message.reply_document(document=file, caption="🗃️ База данных")


def reset_tokens():
    """Сброс токенов для всех пользователей"""
    global db
    for user_id in db.keys():
        db[user_id]["tokens"] = MAX_TOKENS_PER_DAY
    save_db(db)


# Планировщик сброса токенов
scheduler = AsyncIOScheduler(timezone=pytz.timezone("Europe/Moscow"))
scheduler.add_job(reset_tokens, 'cron', hour=11, minute=0)
scheduler.start()

# Запуск бота
app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler('start', start))
app.add_handler(CommandHandler('tokens', show_tokens))
app.add_handler(CommandHandler('mode', switch_model))
app.add_handler(CommandHandler('help', help_command))
app.add_handler(CommandHandler('admin', admin_menu))  # Админ команда
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
app.add_handler(MessageHandler(filters.COMMAND, unknown_command))

app.run_polling()
