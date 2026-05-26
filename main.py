# context.application.user_data[user_id] найти user_data конкретного пользователя

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    CallbackQueryHandler,
    ConversationHandler,
    InvalidCallbackData,
    ApplicationBuilder,
    MessageHandler,
    CommandHandler,
    ContextTypes,
    filters,
    # JobQueue,
    # Job
)
import asyncio
from tclient import TClient, AddContactInvalid
from tclient import errors as telethon_errors
from functools import wraps
import sqlite3
import json
import logging, sys, os
import html
import traceback
import random
import math
from datetime import datetime, timedelta, timezone
from telegram.constants import ParseMode

from zoneinfo import ZoneInfo
from apscheduler.events import EVENT_JOB_REMOVED, EVENT_JOB_ADDED, JobEvent
from loguru import logger
from job_serialization import save_jobs_to_file, restore_jobs_from_file

# logger = logging.getLogger(__name__)

logging.basicConfig(stream=sys.stderr, level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telethon").setLevel(logging.INFO)

from warnings import filterwarnings
from telegram.warnings import PTBUserWarning
filterwarnings(action="ignore", message=r".*CallbackQueryHandler", category=PTBUserWarning)

from dotenv import load_dotenv
load_dotenv()

TOKEN = os.getenv("TOKEN") # os.environ["TOKEN"]
ADMINS = list(map(int, os.getenv("ADMINS", "").split(",")))
DEVELOPER = os.getenv("DEVELOPER")
BOT_DB = "broadcast.db"
(
BROADCAST, ACTIVE_BROADCAST, ADD_ADMIN, TGLOGIN,
CHOOSE_BROADCAST,
ADD_ADMIN, ADD_ADMIN_COMPLETE,
ENTER_CONTACT, ENTER_TEXT, ENTER_TIME, ENTER_DAYS,
ENTER_PHONE, ENTER_PASSWORD, ENTER_CODE, TGLOGIN_FINISH,
CONTINUE, CANCEL, RIGHT, LEFT, MENU
) = range(20)

BROADCAST_INFO = "Контакт: %(contact)s\nТекст: \n%(text)s\n\nНачало: %(first)s, Конец: %(last)s"
DFORMAT = "%d.%m.%Y | %H:%M" # "%d.%m.%Y | %H:%M:%S"
MSCZONE = ZoneInfo("Europe/Moscow")
FILEJOBS = "jobs.pkl"
job_queue = None

# CANSIGN = True
# with open('FILE.json') as file:
#     json_data = json.load(file)

api_id = os.getenv("API_ID")
api_hash = os.getenv("API_HASH")
session_dir = "sessions"
# session = 'user'
clients: dict[int, TClient] = {}
# client = TelegramClient(session, api_id, api_hash) # loop=asyncio.get_running_loop()

os.makedirs(session_dir, exist_ok=True)

cancel_btn = [[InlineKeyboardButton("Отмена", callback_data=str(CANCEL))]]
menu_btn = [[InlineKeyboardButton("Главное меню", callback_data=(str(MENU)))]]

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = "".join(tb_list)
    update_str = update.to_dict() if isinstance(update, Update) else str(update)
    message = (
        "При обработке update возникла ошибка: \n"
        f"<pre>update = {html.escape(json.dumps(update_str, indent=2, ensure_ascii=False))}"
        "</pre>\n"
        f"<pre>context.chat_data = {html.escape(str(context.chat_data))}</pre>\n"
        f"<pre>context.user_data = {html.escape(str(context.user_data))}</pre>\n"
        f"<pre>context.user_data = {html.escape(str(context.bot_data))}</pre>\n"
        f"<pre>{html.escape(tb_string)}</pre>"
    )

    await context.bot.send_message(
        chat_id=DEVELOPER, text=message, parse_mode=ParseMode.HTML
    )

def detect_error(func):
    @wraps(func)
    async def wrapped(update, context, *args, **kwargs):
        try:
            return await func(update, context, *args, **kwargs)
        except BaseException as err:
            await update.message.reply_text(
                "Извините, произошла непредвиденная ошибка. Попробуйте снова.")
            text = f'Ошибка в функции {func.__name__}: {err}'
            await context.bot.send_message(479917441, text)
            logging.info(text)
            return
    return wrapped

def restricted(func):
    @wraps(func)
    async def wrapped(update: Update, context, *args, **kwargs):
        user_id = int(update.effective_user.id)
        connection = sqlite3.connect(BOT_DB)
        cursor = connection.cursor()
        db_admins = cursor.execute("SELECT * FROM admins;")
        db_admins = [id[0] for id in db_admins]
        connection.close()
        if user_id in ADMINS or user_id in db_admins:
            return await func(update, context, *args, **kwargs)
        else:
            await update.effective_message.reply_text('Извините, доступ к боту закрыт.')
            logging.info(f"Неавторизованный доступ запрещен для {user_id}.")
            return
    return wrapped

# @detect_error
@restricted
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_data = context.user_data
    userid = update.effective_user.id
    username = update.effective_user.username
    session = f"{session_dir}/{userid}"
    if not clients.get(userid):
        # Если искать через setdefault, то кажется он в любом случае создает объект переданный в default
        clients[userid] = await TClient.create(session, api_id, api_hash, username, userid)
    # clients.setdefault(userid, await TClient.create(session, api_id, api_hash, username, userid))
    autorized = await clients[userid].is_authorized()

    # logging.info(f"Пользователь открыл меню: {username} {userid}")

    keyboard = [[InlineKeyboardButton("Создать рассылку", callback_data=str(BROADCAST))],
                [InlineKeyboardButton("Список активных рассылок", callback_data=str(ACTIVE_BROADCAST))],
                [InlineKeyboardButton("Добавить админа", callback_data=str(ADD_ADMIN))],
                [InlineKeyboardButton("Вход в аккаунт", callback_data=str(TGLOGIN))]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    autorized_text = "Аккаунт авторизован." if autorized else "Аккаунт неавторизован."
    text = ("Добро пожаловать !\n" + autorized_text)
    if not update.callback_query:
        await update.message.reply_text(text=text, reply_markup=reply_markup)
    else:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text=text, reply_markup=reply_markup)
    return ConversationHandler.END
# BROADCAST
async def enter_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_data = context.user_data
    userid = update.effective_user.id
    query = update.callback_query
    await query.answer()
    text = "Введите username или номер телефона:"
    # await update.effective_user.send_message(text)
    reply_markup = InlineKeyboardMarkup(cancel_btn)
    await query.edit_message_text(text=text, reply_markup=reply_markup)
    return ENTER_CONTACT

async def enter_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_data = context.user_data
    userid = update.effective_user.id
    user_data["broadcast_contact"] = update.message.text
    text = "Текст рассылки: "
    reply_markup = InlineKeyboardMarkup(cancel_btn)
    await update.effective_user.send_message(text, reply_markup=reply_markup)
    return ENTER_TEXT

async def enter_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_data = context.user_data
    userid = update.effective_user.id
    user_data["broadcast_text"] = update.message.text
    text = "Время рассылки в формате чч:мм (00:00):"
    reply_markup = InlineKeyboardMarkup(cancel_btn)
    await update.effective_user.send_message(text, reply_markup=reply_markup)
    return ENTER_TIME

async def enter_days(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_data = context.user_data
    userid = update.effective_user.id
    user_data["broadcast_time"] = update.message.text
    text = "Сколько дней повторять:"
    reply_markup = InlineKeyboardMarkup(cancel_btn)
    await update.effective_user.send_message(text, reply_markup=reply_markup)
    return ENTER_DAYS

async def broadcast_finish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_data = context.user_data
    username = update.effective_user.username
    userid = update.effective_user.id
    broadcast_days = update.message.text

    # тут нужен try/except на формат времени, пользователь мог не то время ввести
    hhmm = datetime.strptime(user_data["broadcast_time"], "%H:%M").time()
    first = datetime.now(MSCZONE).replace(hour=hhmm.hour, minute=hhmm.minute, second=0)
    last = first.replace(hour=23, minute=59) + timedelta(days=int(broadcast_days))
    data = {"username_creator": username,
            "userid_creator": userid,
            "contact": user_data["broadcast_contact"],
            "text": user_data["broadcast_text"],
            "first": first.strftime(DFORMAT),
            "last": last.strftime(DFORMAT)}
    job = context.job_queue.run_repeating(broadtask, interval=timedelta(days=1),
                                          first=first, last=last,
                                          data=data, name=None, user_id=userid)
    
    text = "Рассылка добавлена в очередь!\n" + (BROADCAST_INFO % data)
    reply_markup = InlineKeyboardMarkup(menu_btn)
    await update.effective_user.send_message(text, reply_markup=reply_markup)
    # return ConversationHandler.END

async def broadtask(context: ContextTypes.DEFAULT_TYPE) -> None:
    job = context.job
    userid = job.user_id
    session = f"{session_dir}/{userid}"
    # clients.setdefault(userid, await TClient.create(session, api_id, api_hash,
    #                                    username=job.data["username_creator"],
    #                                    userid=job.data["userid_creator"]))
    if not clients.get(userid):
        clients[userid] = await TClient.create(session, api_id, api_hash, username=job.data["username_creator"], serid=job.data["userid_creator"])

    try:
        await asyncio.sleep(random.randint(1, 60))
        await clients[userid].send_message(job.data["contact"], job.data["text"])
        text = "Сообщение доставлено:\n" + (BROADCAST_INFO % job.data)
        logging.info(f"broadtask | Сообщение доставлено {job.data}")
    except BaseException as err:
        text = f"Сообщение не доставлено для {job.data["contact"]}:\n{err.args[0]}"
    
    # Логирование в избранное аккаунта, который отвечает за рассылку
    # try: await clients[userid].send_message("me", text)
    # except: pass
    # Уведомление пользователю, который создал рассылку
    try:  await context.bot.send_message(chat_id=userid, text=text)
    except: pass
# ACTIVE BROADCAST
async def active_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_data = context.user_data
    query = update.callback_query
    page = user_data.setdefault("broadcast_page", 0)
    if query.data == str(LEFT): page -= 1
    elif query.data == str(RIGHT): page += 1
    max_len = 3
    # print("jobs", len(context.job_queue.jobs()), context.job_queue.jobs())
    jobs = context.job_queue.jobs()[page*max_len:(page+1)*max_len]
    # print('sort jobs', jobs)
    arrows = [[]]
    if page > 0:
        arrows[0].append(InlineKeyboardButton("⬅️", callback_data=str(LEFT)))
    if page < len(context.job_queue.jobs()) / max_len - 1:
        arrows[0].append(InlineKeyboardButton("➡️", callback_data=str(RIGHT)))
    if not jobs:
        text = "Активных рассылок нет."
    else:
        text = "Список активных рассылок:"
    keyboard = []
    for job in jobs:
        id = job.job.id
        time = str(datetime.strptime(job.data['first'], DFORMAT).time())[:-3]
        btn_txt = f"{job.data['contact']} | {time}"
        keyboard.append([InlineKeyboardButton(text=btn_txt, callback_data=f"job-{id}")])
    if arrows[0]: keyboard += arrows
    reply_markup = InlineKeyboardMarkup(keyboard + menu_btn)
    await query.answer()
    await query.edit_message_text(text=text, reply_markup=reply_markup)
    user_data["broadcast_page"] = page
    return ACTIVE_BROADCAST

async def choose_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_data = context.user_data
    jobs = context.job_queue.jobs()
    query = update.callback_query
    _, id = query.data.split("-")
    job = next((job for job in jobs if job.id == id), None)
    await query.answer()
    if not job:
        await update.effective_user.send_message("Данной рассылки больше не существует.")
    else:
        keyboard = [[InlineKeyboardButton("Удалить", callback_data=f"deljob-{job.job.id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        text = BROADCAST_INFO % job.data
        await update.effective_user.send_message(text, reply_markup=reply_markup)
    # return ACTIVE_BROADCAST

async def delete_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_data = context.user_data
    jobs = context.job_queue.jobs()
    query = update.callback_query
    _, id = query.data.split("-")
    job = next((job for job in jobs if job.id == id), None)
    if not job:
        text = "Данной рассылки больше не существует."
    else:
        job.schedule_removal()
        text = "Рассылка удалена"
    reply_markup = InlineKeyboardMarkup(menu_btn)
    await query.answer()
    await query.edit_message_text(text, reply_markup=reply_markup)
#ADMIN
async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_data = context.user_data
    text = "Введите user_id (получить можно здесь @ScanIDBot):"
    await query.answer()
    # await update.effective_user.send_message(text)
    reply_markup = InlineKeyboardMarkup(cancel_btn)
    await query.edit_message_text(text=text, reply_markup=reply_markup)
    return ADD_ADMIN

async def add_admin_complete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_data = context.user_data
    message = update.message.text.replace(" ", "")
    if message.isnumeric():
        connection = sqlite3.connect(BOT_DB)
        cursor = connection.cursor()
        cursor.execute("INSERT OR IGNORE INTO admins (userid) VALUES (%s)" % message)
        connection.commit()
        connection.close()
        text = "Админ добавлен!"
        logging.info(f"Админ {message} добавлен в базу данных {BOT_DB}")
    else:
        text = "Введите только цифры"
    reply_markup = InlineKeyboardMarkup(menu_btn)
    await update.effective_user.send_message(text, reply_markup=reply_markup)
    # return ConversationHandler.END
# LOGIN
async def tglogin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    userid = update.effective_user.id
    username = update.effective_user.username
    session = f"{session_dir}/{userid}"
    query = update.callback_query
    await query.answer()
    text = "Введите номер телефона: "
    if clients.get(userid):
        del clients[userid]
    clients[userid] = await TClient.create(session, api_id, api_hash, username=username, userid=userid)
    reply_markup = InlineKeyboardMarkup(cancel_btn)
    await query.edit_message_text(text=text, reply_markup=reply_markup)
    return ENTER_PHONE

async def enter_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    userid = update.effective_user.id
    user_data = context.user_data
    phone = user_data["phone"] = update.message.text.replace(" ", "")
    reply_markup = InlineKeyboardMarkup(cancel_btn)
    if not phone.replace("+", "").isnumeric():
        await update.effective_user.send_message("Введите корректный номер телефона", reply_markup=reply_markup)
        return ENTER_PHONE
    try:
        phone_code_hash = await clients[userid].send_code(phone)
    except BaseException as err:
        # reply_markup = InlineKeyboardMarkup(menu_btn)
        await update.effective_user.send_message(err.args[0], reply_markup=reply_markup) 
        return ConversationHandler.END

    user_data["phone_code_hash"] = phone_code_hash
    text = "Введите код авторизации, предварительно добавьте после второй цифры тире. Пример: 31-471:"
    await update.effective_message.reply_text(text=text, reply_markup=reply_markup)
    return ENTER_CODE

async def try_sign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    userid = update.effective_user.id
    user_data = context.user_data
    phone = user_data["phone"]
    code = update.message.text
    code = code.replace("-", "")
    phone_code_hash = user_data["phone_code_hash"]
    reply_markup = InlineKeyboardMarkup(cancel_btn)
    try:
        await clients[userid].sign(phone, code, phone_code_hash=phone_code_hash)
        return await tglogin_finish(update, context)
    except telethon_errors.SessionPasswordNeededError:
        text = ("Введите пароль от телеграм-аккаунта:\n"
                "(Осторожно, пароль передается открытым незашифрованным способом!)")
        await update.effective_user.send_message(text, reply_markup=reply_markup)
        return ENTER_PASSWORD
    except BaseException as err:
        await update.effective_user.send_message(err.args[0])
        return ConversationHandler.END

async def enter_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    userid = update.effective_user.id
    user_data = context.user_data
    password = update.message.text
    reply_markup = InlineKeyboardMarkup(menu_btn)
    if not await clients[userid].is_connected():
        await update.message.reply_text(text="Сессия авторизации прервана. Попробуйте снова.")
        return ConversationHandler.END
    try:
        await clients[userid].sign(password=password)
        await clients[userid].save_phone()
        clients[userid].disconnect()
    except BaseException as err:
        await update.effective_user.send_message(err.args[0], reply_markup=reply_markup)
        return ConversationHandler.END
    return await tglogin_finish(update, context)

async def tglogin_finish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    userid = update.effective_user.id
    user_data = context.user_data
    text = "Авторизация успешно завершена."
    reply_markup = InlineKeyboardMarkup(menu_btn)
    await update.message.reply_text(text=text, reply_markup=reply_markup)
    return ConversationHandler.END

# async def mytask(context: ContextTypes.DEFAULT_TYPE) -> None:
#     job = context.job
#     logging.info(f"mytask: {job}")
#     context.job_queue.run_once(mytask2, job_kwargs=job)

# async def mytask2(context: ContextTypes.DEFAULT_TYPE) -> None:
#     job = context.job
#     logging.info(f"mytask2: {job}")

@restricted
async def test(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Не забыть всегда указывать таймзону UTC во времени
    # Если есть переход на летнее время, то это как-то отдельно надо обрабатывать или писать
    userid = update.effective_user.id
    user_data = context.user_data
    now = datetime.now()
    tenmin = now + timedelta(minutes=10)
    # nowutc = datetime.now(timezone.utc) + timedelta(seconds=20)
    # context.job_queue.run_once(mytask, when=nowutc.astimezone(ZoneInfo("Japan")))
    # context.job_queue.run_repeating(mytask, interval=timedelta(days=1),
    #                                 first=datetime.now(MSCZONE) - timedelta(days=2), name="TEST1")
    # context.job_queue.run_once(mytask, 60)

async def handle_invalid_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()
    text="Извините, кнопка устарела 😕 Пожалуйста, введите повторно команду /start"
    await update.effective_message.edit_text(text)

async def command_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = "Отмена."
    await update.effective_user.send_message(text)
    return ConversationHandler.END

async def button_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text('Отмена. Нажмите /start чтобы начать сначала.')
    return ConversationHandler.END

async def init(context: ContextTypes.DEFAULT_TYPE):
    if not os.path.exists(BOT_DB):
        connection = sqlite3.connect(BOT_DB)
        cursor = connection.cursor()
        cursor.execute("""CREATE TABLE admins
                    (userid BIGINT NOT NULL,
                    UNIQUE (userid)
        );""")
        # connection.commit()
        connection.close()
        
    commands = [
        ("start", "главное меню"),
    ]
    await context.bot.set_my_commands(commands)
    

def scheduler_event_catcher(event: JobEvent):
    logger.debug(
        (f"Scheduler event: {event}, job id: {event.job_id}, "
         f"jobstore name: {event.jobstore}") # current job queue: {job_queue}
    )
    if job_queue:
        logger.info(f"job queue is defined, saving jobs to {FILEJOBS}")
        save_jobs_to_file(job_queue, FILEJOBS)
    else:
        logger.warning(f"job queue is not defined")


def main() -> None:
    global job_queue
    app = ApplicationBuilder().token(TOKEN).arbitrary_callback_data(True).post_init(init).build()
    app.job_queue.scheduler.add_listener(
        scheduler_event_catcher, EVENT_JOB_REMOVED | EVENT_JOB_ADDED)
    conv_broadcast = ConversationHandler(
        entry_points=[CallbackQueryHandler(enter_contact, pattern=f"^{BROADCAST}$")],
        states={
            ENTER_CONTACT: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_text)],
            ENTER_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_time)],
            ENTER_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_days)],
            ENTER_DAYS: [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_finish)],
        },
        fallbacks=[CommandHandler('start', start), CallbackQueryHandler(start, pattern=f"^{CANCEL}$"),
                                    CallbackQueryHandler(start, pattern=f"^{MENU}$")],
        map_to_parent={}
    )
    conv_active_broadcast = ConversationHandler(
        entry_points=[CallbackQueryHandler(active_broadcast, pattern=f"^{ACTIVE_BROADCAST}$")],
        states={
            ACTIVE_BROADCAST: [CallbackQueryHandler(active_broadcast, pattern=f"^{RIGHT}$"),
                               CallbackQueryHandler(active_broadcast, pattern=f"^{LEFT}$"),
                               CallbackQueryHandler(choose_broadcast, pattern=f"^(job-)")],
        },
        fallbacks=[CommandHandler('start', start), CallbackQueryHandler(start, pattern=f"^{CANCEL}$"),
                                    CallbackQueryHandler(start, pattern=f"^{MENU}$")],
    )
    conv_add_admin = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_admin, pattern=f"^{ADD_ADMIN}$")],
        states={
            ADD_ADMIN: [MessageHandler(filters.TEXT & ~filters.COMMAND ,add_admin_complete)],
        },
        fallbacks=[CommandHandler('start', start), CallbackQueryHandler(start, pattern=f"^{CANCEL}$"),
                                    CallbackQueryHandler(start, pattern=f"^{MENU}$")],
    )
    conv_tglogin = ConversationHandler(
        entry_points=[CallbackQueryHandler(tglogin, pattern=f"^{TGLOGIN}$")],
        states={
            ENTER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_code)],
            ENTER_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, try_sign)],
            ENTER_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_password)]
        },
        fallbacks=[CommandHandler('start', start), CallbackQueryHandler(start, pattern=f"^{CANCEL}$"),
                                    CallbackQueryHandler(start, pattern=f"^{MENU}$")],
        # map_to_parent={}
    )
    # app.add_error_handler(error_handler)
    # app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, user_message))
    # app.add_handler(MessageHandler(filters.ALL, user_message))
    app.add_handler(conv_broadcast)
    app.add_handler(conv_active_broadcast)
    app.add_handler(conv_add_admin)
    app.add_handler(conv_tglogin)
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('test', test))
    app.add_handler(CallbackQueryHandler(delete_broadcast, pattern=f"^(deljob-)"))
    # app.add_handler(MessageHandler(filters=filters.Regex("^/start$")))
    app.add_handler(
        CallbackQueryHandler(handle_invalid_button, pattern=InvalidCallbackData)
    )
    # app.add_handler(CallbackQueryHandler(click_button))
    job_queue = app.job_queue
    restore_jobs_from_file(job_queue, FILEJOBS)
    # app.job_queue.run_once(set_commands, 0) # не хорошо работает вместе с job_serialization.py
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()