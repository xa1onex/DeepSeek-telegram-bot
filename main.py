import json
from multiprocessing import context
import pytz
import aiohttp
import asyncio
import hashlib
import secrets
from datetime import datetime
from telegram import InputMediaPhoto, InputMediaVideo
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Update, ReplyKeyboardMarkup, InputFile, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters, ConversationHandler, \
    CallbackQueryHandler

TOKEN = '7595932493:AAG7hrJckODArPCX8I2ZZyPj-602xqRPS2c'
API_KEY = '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'
API_URL = 'https://openrouter.ai/api/v1/chat/completions'
MODELS = ['deepseek/deepseek-chat', 'deepseek/deepseek-r1']
CHANNEL_ID = -1002385534325
CHANNEL_LINK = "https://t.me/doublexx_group"
current_model = MODELS[0]
ANNOUNCE_TEXT, ANNOUNCE_CONFIRM = range(2)
ANNOUNCE_MEDIA = range(3)

MAX_TOKENS_PER_DAY = 1000

DB_FILE = "database.json"

ADMIN_USER_ID = 5387020491

def load_db():
    try:
        with open(DB_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
            for user_id in data:
                user_data = data[user_id]
                user_data.setdefault("subscribed", False)
                user_data.setdefault("blacklist", False)
                user_data.setdefault("requests", 0)
                user_data.setdefault("username", None)
                user_data.setdefault("first_name", None)
                user_data.setdefault("last_name", None)
                user_data.setdefault("full_name", None)
                user_data.setdefault("referral_code", "")
                user_data.setdefault("referrals", {})
                user_data.setdefault("referral_count", 0)
                user_data.setdefault("referral_tokens", 0)
                user_data.setdefault("invited_by", None)
                user_data.setdefault("registration_date", "2024-01-01 00:00:00")
                user_data.setdefault("policy_accepted", True)
            return data
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_db(data):
    with open(DB_FILE, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=4)

def reset_tokens():
    global db
    for user_id in db.keys():
        db[user_id]["tokens"] = MAX_TOKENS_PER_DAY
    save_db(db)

def generate_referral_code(user_id):
    hash_part = hashlib.sha256(str(user_id).encode()).hexdigest()[:4]
    random_part = secrets.token_hex(2)[:4]
    return f"{hash_part}{random_part}".upper()

def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_USER_ID

def get_start_keyboard():
    keyboard = [
        [InlineKeyboardButton("📜 Privacy policy",
                            url="https://telegra.ph/Konfidencialnost-i-usloviya-02-01")],
        [InlineKeyboardButton("✅ I agree", callback_data="accept_policy")]
    ]
    return InlineKeyboardMarkup(keyboard)

def is_user_exists(user_id):
    return str(user_id) in db

def extract_arguments(text):
    return ' '.join(text.split()[1:]) if len(text.split()) > 1 else ''

def get_user_id_by_username(username: str):
    if not username or not username.startswith("@"):
        return None

    username = username[1:].lower()

    for user_id, user_data in db.items():
        user_username = user_data.get("username", "")
        if user_username is None:
            continue
        if user_username.lower() == username:
            return int(user_id)
    return None

db = load_db()

async def chat_with_model(user_id, messages):
    global db
    if db[user_id]["tokens"] <= 0:
        return "❌ You have run out of tokens for today. Try it tomorrow!"

    async with aiohttp.ClientSession() as session:
        async with session.post(
                API_URL,
                headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": current_model,
                    "messages": messages[-15:],  # Ограничиваем историю
                    "max_tokens": min(db[user_id]["tokens"], 1000),  # Не больше оставшихся
                    "temperature": 0.6,
                }
        ) as response:
            if response.status != 200:
                return "API error. Try again later."
            result = await response.json()
            answer = result.get("choices", [{}])[0].get("message", {}).get("content", "There is no response.")

            tokens_used = len(answer.split()) * 1.5
            db[user_id]["tokens"] -= int(tokens_used)
            save_db(db)

            return answer


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = str(user.id)
    args = context.args

    referral_code = None
    if args:
        for arg in args:
            if arg.startswith('ref='):
                referral_code = arg.split('=')[1]
                break

    is_new_user = False
    if user_id not in db:
        is_new_user = True
        db[user_id] = {
            "tokens": MAX_TOKENS_PER_DAY,
            "requests": 0,
            "blacklist": False,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "full_name": user.full_name,
            "registration_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "policy_accepted": False,
            "subscribed": False,
            "referral_code": generate_referral_code(user_id),
            "referrals": {},
            "referral_count": 0,
            "referral_tokens": 0,
            "invited_by": referral_code,
        }
        save_db(db)

        welcome_message = "👋 Welcome!"
        if referral_code:
            inviter_username = None
            for uid, data in db.items():
                if data["referral_code"] == referral_code and uid != user_id:
                    inviter_username = data.get("username")
                    break

            if inviter_username:
                welcome_message += f"\n\nI invited you @{inviter_username}."

        welcome_message += (
            "\n\nTo get additional tokens and use the bot, "
            "read the privacy policy:"
        )

        await update.message.reply_text(
            welcome_message,
            reply_markup=get_start_keyboard()
        )
    else:
        user_data = db[user_id]
        if not user_data["policy_accepted"]:
            await update.message.reply_text(
                "⚠️ Please accept the Privacy policy to continue.:",
                reply_markup=get_start_keyboard()
            )
        elif not user_data["subscribed"]:
            await show_subscription_request(user.id, context)
        else:
            await show_main_menu(user.id, context)


async def ref_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = str(user.id)

    if not is_user_exists(user_id):
        await update.message.reply_text("❌ First, register using /start")
        return

    user_data = db[user_id]
    ref_code = user_data["referral_code"]
    ref_link = f"https://t.me/{context.bot.username}?start=ref={ref_code}"

    text = (
        f"🎁 Referral program\n\n"
        f"🔗 Your link:\n{ref_link}\n\n"
        f"👥 Invited: {user_data['referral_count']} people.\n"
        f"🪙 Tokens received: {user_data['referral_tokens']}\n\n"
        f"For each friend you get +100 tokens, and a friend gets +100 when registering!"
    )

    keyboard = [
        [InlineKeyboardButton("📤 To share",
                              url=f"https://t.me/share/url?url={ref_link}&text=Join us and get a bonus!")],
    ]
    await update.message.reply_text(text,
                                    reply_markup=InlineKeyboardMarkup(keyboard),
                                    disable_web_page_preview=True)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    user_id = str(user.id)

    await query.answer()

    if query.data == "accept_policy":
        db[user_id]["policy_accepted"] = True
        save_db(db)

        if await check_subscription(user.id, context):
            db[user_id]["subscribed"] = True
            save_db(db)
            await show_main_menu(user.id, context)

            inviter_code = db[user_id].get("invited_by")
            if inviter_code:
                for uid, data in db.items():
                    if data["referral_code"] == inviter_code and uid != user_id:
                        db[uid]["referral_count"] += 1
                        db[uid]["referral_tokens"] += 100
                        db[uid]["tokens"] += 100
                        db[user_id]["tokens"] += 100
                        db[uid]["referrals"][user_id] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        save_db(db)
                        try:
                            await context.bot.send_message(
                                uid,
                                f"🎉 A new user has signed up for your link!\n"
                                f"+100 tokens for you and your friend!"
                            )
                            await query.edit_message_text(
                                f"You have received +100 tokens for registration via a referral link!"
                            )
                        except Exception as e:
                            print(f"Error sending notification: {e}")
                        break
        else:
            await show_subscription_request(user.id, context)

    elif query.data == "check_subscription":
        if await check_subscription(user.id, context):
            db[user_id]["subscribed"] = True
            save_db(db)
            await show_main_menu(user.id, context)
            await query.edit_message_text("✅ Thanks for subscribing!")
        else:
            await query.answer("❌ You haven't subscribed to the channel yet!", show_alert=True)

    elif query.data == "check_ref":
        user_data = db.get(user_id, {})
        if not user_data:
            await query.answer("❌ You are not registered!", show_alert=True)
            return

        original_text = query.message.text

        updated_text = original_text.replace(
            f"👥 Invited: {user_data.get('referral_count_prev', 0)}",
            f"👥 Invited: {user_data.get('referral_count', 0)}"
        ).replace(
            f"🪙 Tokens received: {user_data.get('referral_tokens_prev', 0)}",
            f"🪙 Tokens received: {user_data.get('referral_tokens', 0)}"
        )

        db[user_id]["referral_count_prev"] = user_data.get("referral_count", 0)
        db[user_id]["referral_tokens_prev"] = user_data.get("referral_tokens", 0)
        save_db(db)

        await query.edit_message_text(updated_text)


async def check_subscription(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        member = await context.bot.get_chat_member(
            chat_id=CHANNEL_ID,
            user_id=user_id
        )
        return member.status in ["member", "administrator", "creator"]
    except BadRequest:
        return False


async def show_subscription_request(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📢 Subscribe to the channel", url=CHANNEL_LINK)],
        [InlineKeyboardButton("✅ I have subscribed", callback_data="check_subscription")]
    ]
    markup = InlineKeyboardMarkup(keyboard)

    await context.bot.send_message(
        chat_id=chat_id,
        text="📢 To use the bot, you need to subscribe to our channel!",
        reply_markup=markup
    )


async def show_tokens(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_chat.id)
    tokens_left = db.get(user_id, {}).get("tokens", MAX_TOKENS_PER_DAY)
    await update.message.reply_text(f"📊 You have {tokens_left} tokens left for today.")


async def switch_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_model
    current_model = MODELS[1] if current_model == MODELS[0] else MODELS[0]
    await update.message.reply_text(f"🔄 The model is now used: {current_model}")


async def show_main_menu(chat_id: int, context: ContextTypes.DEFAULT_TYPE, is_admin: bool = False):
    if is_admin:
        keyboard = [
            ["📊 Статистика", "🆘 Помощь для админ"],
            ["📂 Data"]
        ]
    else:
        keyboard = []

    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await context.bot.send_message(
        chat_id=chat_id,
        text="👋 Hi!\n "
             "I'm ready to work, what are we going to do?",
        reply_markup=reply_markup
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = str(user.id)

    if not await pre_checks(update, context):
        return

    if not db.get(user_id, {}).get("subscribed", False):
        await show_subscription_request(user.id, context)
        return

    if user_id in db and not db[user_id].get("policy_accepted", False):
        await update.message.reply_text(
            "⚠️ Please accept the privacy policy, "
            "to continue using the bot.",
            reply_markup=get_start_keyboard()
        )
        return

    db[user_id].update({
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "full_name": user.full_name
    })
    save_db(db)

    if db.get(user_id, {}).get("blacklist", False):
        await update.message.reply_text("❌ You are blocked!")
        return

    db[user_id]["requests"] = db.get(user_id, {}).get("requests", 0) + 1
    save_db(db)

    user_message = update.message.text

    if user_message == "📊 Остаток токенов":
        await show_tokens(update, context)
    elif user_message == "🔄 Сменить модель":
        await switch_model(update, context)
    elif user_message == "🆘 Помощь":
        await help_command(update, context)
    elif user_message == "📊 Статистика":
        await admin_stats(update, context)
    elif user_message == "🆘 Помощь для админ":
        await help_admin(update, context)
    elif user_message == "📂 Data":
        await data_command(update, context)
    elif user_message == "⬅️ Назад":
        await start(update, context)
    else:
        if db[user_id]["tokens"] <= 0:
            await update.message.reply_text("❌ You have run out of tokens for today. Try it tomorrow!")
            return

        asyncio.create_task(context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING))

        response = await chat_with_model(user_id, [{"role": "user", "content": user_message}])
        await update.message.reply_text(response, ParseMode.MARKDOWN)


async def pre_checks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    user_id = str(user.id)

    if user_id not in db:
        await start(update, context)
        return False

    if not db[user_id]["policy_accepted"]:
        await update.message.reply_text(
            "⚠️ Please accept the privacy policy to use the bot:",
            reply_markup=get_start_keyboard()
        )
        return False

    if not db[user_id]["subscribed"] or not await check_subscription(user.id, context):
        await show_subscription_request(user.id, context)
        return False

    if db[user_id]["blacklist"]:
        await update.message.reply_text("❌ You are blocked!")
        return False

    return True


async def check_subscription_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = str(user.id)

    if user_id not in db:
        db[user_id] = {
            "tokens": MAX_TOKENS_PER_DAY,
            "requests": 0,
            "blacklist": False,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "full_name": user.full_name,
            "registration_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "policy_accepted": False,
            "subscribed": False
        }
        save_db(db)

    if await check_subscription(user.id, context):
        db[user_id]["subscribed"] = True
        save_db(db)
        await update.message.reply_text("✅ Thanks for subscribing!")
        await show_main_menu(user.id, context)
    else:
        await update.message.reply_text("❌ You haven't subscribed to the channel yet!")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📌 Teams:\n"
        "💬 Just write a message and I will reply \n"
        "📊 /tokens — Find out the remaining tokens\n"
        "🔄 /mode — Change the model\n"
        "🆘 /help — Help\n"
    )
    await update.message.reply_text(text)


async def help_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📌 Команды:\n"
        "/admin_stats - Статистика по боту\n\n"
        "/data - Выгрузка базы данных\n\n"
        "/user_info @username - Информация пользователя\n\n"
        "/announce @username - Рассылка для пользователей\n\n"
        "/ban @username - Блокировка пользователя\n\n"
        "/help_admin - Помощь по админке"
    )
    await update.message.reply_text(text)


async def admin_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text

    if user.id != ADMIN_USER_ID or update.effective_chat.type != "private":
        return

    if text.startswith(('/a', '/announce', '/alert', '/broadcast', '/notify')):
        await announce_command(update, context)
    elif text.startswith(('/ban', '/block')):
        await ban_command(update, context)


async def announce_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_filter = extract_arguments(update.message.text)

    if not user_filter:
        help_text = (
            "Введите тип рассылки после команды /announce\n\n"
            "Варианты:\n"
            "all - рассылка всем пользователям\n"
            "req1 - рассылка всем, кто сделал хотя бы 1 запрос\n"
            "test - тестовая рассылка только админу\n\n"
            "user_id или @username - Отдельному пользователю"
        )
        await update.message.reply_text(help_text)
        return

    context.user_data['announce_filter'] = user_filter
    await update.message.reply_text("Введите текст сообщения для рассылки.\nq - отмена")
    return ANNOUNCE_TEXT


async def announce_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_filter = context.user_data.get('announce_filter')

    if text.lower() == 'q':
        await update.message.reply_text("Рассылка отменена")
        return ConversationHandler.END

    recipients = []
    if user_filter == "test":
        recipients.append(ADMIN_USER_ID)
    elif user_filter == "all":
        recipients = [int(uid) for uid in db.keys() if uid != str(ADMIN_USER_ID)]
    elif user_filter.startswith("req"):
        min_requests = int(user_filter[3:]) if user_filter[3:].isdigit() else 1
        recipients = [
            int(uid) for uid in db
            if db[uid].get("requests", 0) >= min_requests and uid != str(ADMIN_USER_ID)
        ]
    else:
        if user_filter.startswith("@"):
            user_id = get_user_id_by_username(user_filter)
        elif user_filter.isdigit():
            user_id = int(user_filter)
        else:
            await update.message.reply_text("❌ Неверный формат")
            return ConversationHandler.END

        if not is_user_exists(user_id):
            await update.message.reply_text("❌ Пользователь не найден")
            return ConversationHandler.END

        recipients.append(user_id)

    context.user_data['announce_data'] = {
        'recipients': recipients,
        'text': text
    }
    await update.message.reply_text("Хотите прикрепить фото или видео? (y/n)")
    return ANNOUNCE_MEDIA


async def announce_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    answer = update.message.text.lower()

    if answer == 'y':
        await update.message.reply_text("Пожалуйста, отправьте фото или видео.")
        return ANNOUNCE_MEDIA
    elif answer == 'n':
        if 'announce_media' in context.user_data:
            del context.user_data['announce_media']
        return await announce_confirm(update, context)
    else:
        await update.message.reply_text("Пожалуйста, ответьте 'y' или 'n'.")
        return ANNOUNCE_MEDIA


async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        media_type = "photo"
        media_file_id = update.message.photo[-1].file_id
    elif update.message.video:
        media_type = "video"
        media_file_id = update.message.video.file_id
    else:
        await update.message.reply_text("Пожалуйста, отправьте фото или видео.")
        return ANNOUNCE_MEDIA

    context.user_data['announce_media'] = {
        'type': media_type,
        'file_id': media_file_id
    }

    return await announce_confirm(update, context)


async def announce_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = context.user_data.get('announce_data')
    text = data.get('text')
    recipients = data.get('recipients')
    media = context.user_data.get('announce_media', None)

    if not recipients:
        await update.message.reply_text("❌ Нет получателей для рассылки.")
        return ConversationHandler.END

    success = 0
    total = len(recipients)

    admin_log = []
    for uid in recipients:
        user_info = db.get(str(uid), {})
        try:
            if media and 'file_id' in media:
                if media['type'] == 'photo':
                    await context.bot.send_photo(
                        chat_id=uid,
                        photo=media['file_id'],
                        caption=text,
                        parse_mode="HTML"
                    )
                elif media['type'] == 'video':
                    await context.bot.send_video(
                        chat_id=uid,
                        video=media['file_id'],
                        caption=text,
                        parse_mode="HTML"
                    )
            else:
                await context.bot.send_message(
                    uid,
                    text,
                    parse_mode="HTML"
                )
            success += 1
            admin_log.append(
                f"✅ {user_info.get('full_name')} "
                f"(@{user_info.get('username')}) "
                f"[ID: {uid}]"
            )
            await asyncio.sleep(0.5)
        except Exception as e:
            admin_log.append(
                f"❌ {user_info.get('full_name')} "
                f"(@{user_info.get('username')}) "
                f"[ID: {uid}] | Ошибка: {str(e)}"
            )
    log_text = "\n".join(admin_log)
    await update.message.reply_text(
        f"✅ Рассылка завершена\nДоставлено: {success}/{total}"
    )
    if 'announce_data' in context.user_data:
        del context.user_data['announce_data']
    if 'announce_media' in context.user_data:
        del context.user_data['announce_media']

    return ConversationHandler.END


async def user_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_chat.id

    if user_id != ADMIN_USER_ID:
        await update.message.reply_text("❌ You don't have access to this command.")
        return

    args = context.args
    if not args:
        await update.message.reply_text("Использование: /user_info @username или user_id")
        return

    target = args[0]
    user_id_to_check = None

    if target.startswith("@"):
        user_id_to_check = get_user_id_by_username(target)
        if not user_id_to_check:
            await update.message.reply_text("❌ Пользователь с таким username не найден.")
            return
    elif target.isdigit():
        user_id_to_check = int(target)
        if str(user_id_to_check) not in db:
            await update.message.reply_text("❌ Пользователь с таким ID не найден.")
            return
    else:
        await update.message.reply_text("❌ Неверный формат. Используйте @username или user_id.")
        return

    user_data = db[str(user_id_to_check)]
    response = (
        f"📋 Информация о пользователе:\n\n"
        f"🆔 ID: {user_id_to_check}\n"
        f"👤 Имя: {user_data.get('full_name', 'Не указано')}\n"
        f"📛 Юзернейм: @{user_data.get('username', 'Не указан')}\n"
        f"📅 Дата регистрации: {user_data.get('registration_date', 'Не указана')}\n"
        f"🕒 Последняя активность: {user_data.get('last_activity', 'Не указана')}\n"
        f"📝 Запросов сделано: {user_data.get('requests', 0)}\n"
        f"🪙 Токенов осталось: {user_data.get('tokens', 0)}\n"
        f"🔗 Реферальный код: {user_data.get('referral_code', 'Не сгенерирован')}\n"
        f"👥 Приглашено пользователей: {user_data.get('referral_count', 0)}\n"
        f"🚫 Статус блокировки: {'Заблокирован' if user_data.get('blacklist', False) else 'Активен'}"
    )

    await update.message.reply_text(response)


async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("Укажите user_id или @username")
        return

    target = args[0]
    user_id = None

    if target.startswith("@"):
        user_id = get_user_id_by_username(target)
    elif target.isdigit():
        user_id = int(target)

    if not user_id or not is_user_exists(user_id):
        await update.message.reply_text("❌ Пользователь не найден")
        return

    db[str(user_id)]["blacklist"] = True
    save_db(db)
    await update.message.reply_text(f"✅ Пользователь {target} заблокирован")


async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_chat.id

    if user_id != ADMIN_USER_ID:
        await update.message.reply_text("❌ You don't have access to this command.")
        return

    total_users = len(db)

    active_users = sum(1 for user in db.values() if user.get("requests", 0) > 0)

    now = datetime.now()
    active_today = sum(
        1 for user in db.values()
        if user.get("last_activity") and (now - datetime.strptime(user["last_activity"], "%Y-%m-%d %H:%M:%S")).days == 0
    )
    active_this_week = sum(
        1 for user in db.values()
        if user.get("last_activity") and (now - datetime.strptime(user["last_activity"], "%Y-%m-%d %H:%M:%S")).days <= 7
    )
    active_this_month = sum(
        1 for user in db.values()
        if user.get("last_activity") and (now - datetime.strptime(user["last_activity"], "%Y-%m-%d %H:%M:%S")).days <= 30
    )

    male_count = sum(1 for user in db.values() if user.get("gender") == "male")
    female_count = sum(1 for user in db.values() if user.get("gender") == "female")
    unknown_gender = total_users - male_count - female_count

    total_requests = sum(user.get("requests", 0) for user in db.values())
    avg_requests_per_user = total_requests / total_users if total_users > 0 else 0

    stats_text = (
        f"📊 Детальная статистика:\n\n"
        f"👥 Всего пользователей: {total_users}\n"
        f"🟢 Активных пользователей: {active_users}\n\n"
        f"📅 Активность:\n"
        f"• За сегодня: {active_today}\n"
        f"• За неделю: {active_this_week}\n"
        f"• За месяц: {active_this_month}\n\n"
        f"👫 Гендерный состав:\n"
        f"• Мужчины: {male_count}\n"
        f"• Женщины: {female_count}\n"
        f"• Не указано: {unknown_gender}\n\n"
        f"📝 Среднее количество запросов на пользователя: {avg_requests_per_user:.1f}"
    )

    await update.message.reply_text(stats_text)


async def data_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_USER_ID:
        return

    file_path = "database.json"

    with open(file_path, "w", encoding="utf-8") as file:
        json.dump(db, file, indent=4, ensure_ascii=False)

    with open(file_path, "rb") as file:
        await context.bot.send_document(chat_id=ADMIN_USER_ID, document=InputFile(file), filename="users_data.json")


async def delete_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_chat.id

    if user_id != ADMIN_USER_ID:
        await update.message.reply_text("❌ You don't have access to this command.")
        return

    args = context.args
    if not args:
        await update.message.reply_text("Использование: /delete_user @username или user_id")
        return

    target = args[0]
    user_id_to_delete = None

    if target.startswith("@"):
        user_id_to_delete = get_user_id_by_username(target)
        if not user_id_to_delete:
            await update.message.reply_text("❌ Пользователь с таким username не найден.")
            return
    elif target.isdigit():
        user_id_to_delete = int(target)
        if str(user_id_to_delete) not in db:
            await update.message.reply_text("❌ Пользователь с таким ID не найден.")
            return
    else:
        await update.message.reply_text("❌ Неверный формат. Используйте @username или user_id.")
        return

    del db[str(user_id_to_delete)]
    save_db(db)
    await update.message.reply_text(f"✅ Пользователь {target} удален из базы данных.")


conv_handler = ConversationHandler(
    entry_points=[CommandHandler(['a', 'announce', 'alert', 'broadcast', 'notify'], announce_command)],
    states={
        ANNOUNCE_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, announce_text)],
        ANNOUNCE_MEDIA: [
            MessageHandler(filters.PHOTO | filters.VIDEO, handle_media),
            MessageHandler(filters.TEXT & ~filters.COMMAND, announce_media)
        ],
        ANNOUNCE_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, announce_confirm)]
    },
    fallbacks=[]
)

scheduler = AsyncIOScheduler(timezone=pytz.timezone("Europe/Moscow"))
scheduler.add_job(reset_tokens, 'cron', hour=11, minute=0)
scheduler.start()

app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(conv_handler)
app.add_handler(CommandHandler('start', start))
app.add_handler(CommandHandler('tokens', show_tokens))
app.add_handler(CommandHandler('mode', switch_model))
app.add_handler(CommandHandler('data', data_command))
app.add_handler(CommandHandler('help', help_command))
app.add_handler(CommandHandler('help_admin', help_admin))
app.add_handler(CommandHandler('delete_user', delete_user))
app.add_handler(CommandHandler('user_info', user_info))
app.add_handler(CommandHandler('ref', ref_command))
app.add_handler(conv_handler)
app.add_handler(MessageHandler(filters.Regex("^📊 Статистика$"), admin_stats))
app.add_handler(MessageHandler(filters.Regex("^⬅️ Назад$"), start))
app.add_handler(MessageHandler(filters.Regex("^🆘 Помощь для админа$"), help_admin))
app.add_handler(CallbackQueryHandler(handle_callback))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
app.add_handler(MessageHandler(filters.ALL, admin_commands))

app.run_polling()
