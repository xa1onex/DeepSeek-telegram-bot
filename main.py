from xml.etree.ElementTree import parse

from telegram import Update, Bot, ChatAction, ReplyKeyboardMarkup, ParseMode
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
import requests
import json

# Токен бота и API-ключ DeepSeek
TOKEN = '7505260246:AAHmg0mZ3apMvYSQPCIrbnmE7AEvN23xDeo'
API_KEY = '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'
API_URL = 'https://openrouter.ai/api/v1/chat/completions'

# Список доступных моделей
MODELS = ['deepseek/deepseek-chat', 'deepseek/deepseek-r1']
current_model = MODELS[0]

# Инициализация бота
bot = Bot(token=TOKEN)
updater = Updater(token=TOKEN, use_context=True)
dispatcher = updater.dispatcher

# Контекст диалога
dialog_context = {}


def process_content(content):
    return content.replace('<think>', '').replace('</think>', '')


def chat_with_model(messages):
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": current_model,
        "messages": messages,
        "stream": False
    }

    response = requests.post(API_URL, headers=headers, json=data)
    if response.status_code != 200:
        return "Ошибка API."

    response_data = response.json()
    return process_content(response_data.get('choices', [{}])[0].get('message', {}).get('content', 'Нет ответа.'))


def start(update: Update, context: CallbackContext):
    keyboard = [['/help', '/clear'], ['/mode']]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Добро пожаловать в бота! Просто напишите запрос, и я отвечу.",
        reply_markup=reply_markup
    )


def clear(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    dialog_context[chat_id] = []
    context.bot.send_message(chat_id=chat_id, text="Контекст диалога очищен.")


def switch_mode(update: Update, context: CallbackContext):
    global current_model
    current_model = MODELS[1] if current_model == MODELS[0] else MODELS[0]
    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"Переключено на модель: {current_model}"
    )


def handle_message(update: Update, context: CallbackContext):
    user_message = update.message.text
    chat_id = update.effective_chat.id

    if chat_id not in dialog_context:
        dialog_context[chat_id] = []
    dialog_context[chat_id].append({"role": "user", "content": user_message})

    context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    response = chat_with_model(dialog_context[chat_id])
    dialog_context[chat_id].append({"role": "assistant", "content": response})

    context.bot.send_message(chat_id=chat_id, text=response, parse_mode=ParseMode.MARKDOWN)

def help_command(update: Update, context: CallbackContext):
    help_text = """
    /start — Запустить бота\n/clear — Очистить контекст диалога\n/mode — Переключение модели\n/help — Показать справку\n\nВНИМАНИЕ!\ndeepseek-r1 умнее и рассудительней чем deepseek-chat, но deepseek-chat быстрее! 
    """
    context.bot.send_message(chat_id=update.effective_chat.id, text=help_text)


def unknown_command(update: Update, context: CallbackContext):
    context.bot.send_message(chat_id=update.effective_chat.id, text="Неизвестная команда.")


# Обработчики команд
dispatcher.add_handler(CommandHandler('start', start))
dispatcher.add_handler(CommandHandler('clear', clear))
dispatcher.add_handler(CommandHandler('mode', switch_mode))
dispatcher.add_handler(CommandHandler('help', help_command))
dispatcher.add_handler(MessageHandler(Filters.text & (~Filters.command), handle_message))
dispatcher.add_handler(MessageHandler(Filters.command, unknown_command))

# Запуск бота
updater.start_polling()
updater.idle()