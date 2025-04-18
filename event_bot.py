import os
import sqlite3
import logging
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
)

# --- Настройка ---
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DB_PATH = str(Path.home() / "telegram_bot_data" / "events.db")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Состояния ConversationHandler
(
    GET_DATETIME,
    GET_TEXT,
    GET_FILE,
    GET_EVENT_ID,
    GET_EDIT_ID,
    EDIT_CHOICE,
    EDIT_DATETIME,
    EDIT_TEXT,
    EDIT_FILE,
    CONFIRM_DELETE,
) = range(10)

# --- Инициализация БД ---
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                datetime TEXT NOT NULL,
                event_text TEXT NOT NULL,
                file_id TEXT,
                file_type TEXT,
                file_name TEXT
            )"""
        )

def parse_datetime(datetime_str):
    try:
        date_part, time_part = datetime_str.split()
        day = int(date_part[:2])
        month = int(date_part[2:4])
        year = 2000 + int(date_part[4:6])
        hour = int(time_part[:2])
        minute = int(time_part[2:4])
        return datetime(year, month, day, hour, minute)
    except (ValueError, IndexError):
        return None

def format_datetime(dt):
    return dt.strftime("%d%m%y %H%M")

def format_display_datetime(dt_str):
    try:
        dt = datetime.strptime(dt_str, "%d%m%y %H%M")
        return dt.strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return dt_str

async def show_events_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    events = context.user_data.get("events_list", [])
    page = context.user_data.get("current_page", 0)
    per_page = 5
    total_pages = (len(events) + per_page - 1) // per_page

    start = page * per_page
    end = start + per_page
    page_events = events[start:end]

    message = f"📋 Ваши события (стр. {page+1}/{total_pages}):\n\n"
    for event_id, dt, text, file_type, file_name in page_events:
        message += f"🆔 {event_id}\n⏰ {format_display_datetime(dt)}: {text}\n"
        if file_type:
            name = file_name if file_name else file_type
            message += f"📎 Файл: {name}\n"
        message += "\n"

    keyboard = []
    if len(events) > per_page:
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("⬅️ Назад", callback_data="prev_page"))
        if end < len(events):
            nav_buttons.append(InlineKeyboardButton("Вперед ➡️", callback_data="next_page"))
        keyboard.append(nav_buttons)

    keyboard.append([InlineKeyboardButton("📥 Скачать файлы", callback_data="get_files")])
    keyboard.append([InlineKeyboardButton("✏️ Редактировать", callback_data="edit_event")])
    keyboard.append([InlineKeyboardButton("❌ Удалить", callback_data="delete_event")])

    if "events_message" in context.user_data:
        try:
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=context.user_data["events_message"],
                text=message,
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return
        except:
            pass

    msg = await update.message.reply_text(
        message, reply_markup=InlineKeyboardMarkup(keyboard)
    )
    context.user_data["events_message"] = msg.message_id

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📅 Бот для учета событий с файлами\n\n"
        "Доступные команды:\n"
        "/add - добавить событие\n"
        "/list - список событий\n"
        "/today - события на сегодня\n"
        "/file - получить файл\n"
        "/edit - редактировать событие\n"
        "/delete - удалить событие\n\n"
        "Формат даты: ДДММГГ ЧЧММ (например, 150624 1430)"
    )

async def add_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📆 Введите дату и время события (ДДММГГ ЧЧММ, например 150624 1430):")
    return GET_DATETIME

async def get_datetime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    datetime_str = update.message.text
    dt = parse_datetime(datetime_str)
    
    if not dt:
        await update.message.reply_text("❌ Неверный формат! Используйте ДДММГГ ЧЧММ (например, 150624 1430)")
        return GET_DATETIME

    if dt < datetime.now():
        await update.message.reply_text("❌ Дата должна быть в будущем!")
        return GET_DATETIME

    context.user_data["datetime"] = format_datetime(dt)
    await update.message.reply_text("✏️ Введите описание события:")
    return GET_TEXT

async def get_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["text"] = update.message.text
    await update.message.reply_text(
        "📎 Прикрепите файл (документ/фото/аудио/голосовое) или нажмите /skip"
    )
    return GET_FILE

async def get_file_attachment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file_id = file_type = file_name = None

    if update.message.document:
        file_id = update.message.document.file_id
        file_type = "document"
        file_name = update.message.document.file_name
    elif update.message.photo:
        file_id = update.message.photo[-1].file_id
        file_type = "photo"
    elif update.message.audio:
        file_id = update.message.audio.file_id
        file_type = "audio"
        file_name = update.message.audio.file_name
    elif update.message.voice:
        file_id = update.message.voice.file_id
        file_type = "voice"

    if file_id:
        await save_event(update, context, file_id, file_type, file_name)
    else:
        await update.message.reply_text(
            "❌ Поддерживаются только документы, фото, аудио и голосовые сообщения"
        )
        return GET_FILE

    return ConversationHandler.END

async def skip_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await save_event(update, context)
    return ConversationHandler.END

async def save_event(update: Update, context: ContextTypes.DEFAULT_TYPE, file_id=None, file_type=None, file_name=None):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """INSERT INTO events 
            (user_id, datetime, event_text, file_id, file_type, file_name) 
            VALUES (?, ?, ?, ?, ?, ?)""",
            (
                update.effective_user.id,
                context.user_data["datetime"],
                context.user_data["text"],
                file_id,
                file_type,
                file_name,
            ),
        )
    msg = "✅ Событие сохранено!" + (" С файлом!" if file_id else "")
    await update.message.reply_text(msg)

async def list_events(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            """SELECT id, datetime, event_text, file_type, file_name 
            FROM events WHERE user_id = ? ORDER BY datetime""",
            (update.effective_user.id,),
        )
        events = cursor.fetchall()

    if not events:
        await update.message.reply_text("📭 Нет сохраненных событий")
        return

    context.user_data["events_list"] = events
    context.user_data["current_page"] = 0
    await show_events_page(update, context)

async def today_events(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = datetime.now().strftime("%d%m%y")

    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            """SELECT id, datetime, event_text, file_type 
            FROM events 
            WHERE user_id = ? AND datetime LIKE ? 
            ORDER BY datetime""",
            (update.effective_user.id, f"{today}%"),
        )
        events = cursor.fetchall()

    if not events:
        await update.message.reply_text(f"📭 Нет событий на сегодня ({datetime.now().strftime('%d.%m.%Y')})")
        return

    message = f"📅 События на сегодня ({datetime.now().strftime('%d.%m.%Y')}):\n\n"
    for event_id, dt, text, file_type in events:
        time_str = format_display_datetime(dt).split()[1] if ' ' in dt else dt
        message += f"🆔 {event_id}\n⏰ {time_str}: {text}\n"
        if file_type:
            message += f"📎 Есть файл\n"
        message += "\n"

    await update.message.reply_text(message)

async def request_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Введите ID события для скачивания файла:")
    return GET_EVENT_ID

async def get_event_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        event_id = int(update.message.text)

        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.execute(
                """SELECT file_id, file_type, file_name 
                FROM events WHERE id = ? AND user_id = ?""",
                (event_id, update.effective_user.id),
            )
            file = cursor.fetchone()

        if not file:
            await update.message.reply_text("❌ Файл не найден")
            return ConversationHandler.END

        file_id, file_type, file_name = file
        caption = f"Файл из события {event_id}" if not file_name else file_name

        if file_type == "document":
            await update.message.reply_document(document=file_id, caption=caption)
        elif file_type == "photo":
            await update.message.reply_photo(photo=file_id, caption=caption)
        elif file_type == "audio":
            await update.message.reply_audio(audio=file_id, caption=caption)
        elif file_type == "voice":
            await update.message.reply_voice(voice=file_id, caption=caption)

    except ValueError:
        await update.message.reply_text("❌ Введите числовой ID события")
        return GET_EVENT_ID
    except Exception as e:
        logger.error(f"Ошибка при получении файла: {e}")
        await update.message.reply_text("⚠️ Ошибка при получении файла")

    return ConversationHandler.END

async def handle_file_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("Введите ID события для скачивания файла:")
    return GET_EVENT_ID

async def edit_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            "SELECT id, datetime, event_text FROM events WHERE user_id = ? ORDER BY datetime",
            (update.effective_user.id,),
        )
        events = cursor.fetchall()

    if not events:
        await update.message.reply_text("📭 Нет событий для редактирования")
        return ConversationHandler.END

    message = "📝 Выберите событие для редактирования (введите ID):\n\n"
    for event_id, dt, text in events:
        message += f"🆔 {event_id}\n⏰ {format_display_datetime(dt)}: {text[:50]}"
        if len(text) > 50:
            message += "..."
        message += "\n\n"

    await update.message.reply_text(message)
    return GET_EDIT_ID

async def get_edit_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        event_id = int(update.message.text)
        context.user_data["edit_id"] = event_id

        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.execute(
                """SELECT datetime, event_text, file_type 
                FROM events WHERE id = ? AND user_id = ?""",
                (event_id, update.effective_user.id),
            )
            event = cursor.fetchone()

        if not event:
            await update.message.reply_text("❌ Событие не найдено")
            return ConversationHandler.END

        keyboard = [
            [InlineKeyboardButton("📅 Дата", callback_data="edit_datetime")],
            [InlineKeyboardButton("✏️ Текст", callback_data="edit_text")],
            [InlineKeyboardButton("📎 Файл", callback_data="edit_file")],
        ]

        await update.message.reply_text(
            "Что вы хотите изменить?",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return EDIT_CHOICE
    except ValueError:
        await update.message.reply_text("❌ Введите числовой ID события")
        return GET_EDIT_ID

async def edit_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    choice = query.data
    event_id = context.user_data["edit_id"]

    if choice == "edit_datetime":
        await query.message.reply_text("Введите новую дату и время (ДДММГГ ЧЧММ, например 150624 1430):")
        return EDIT_DATETIME
    elif choice == "edit_text":
        await query.message.reply_text("Введите новый текст события:")
        return EDIT_TEXT
    elif choice == "edit_file":
        await query.message.reply_text(
            "📎 Прикрепите новый файл (документ/фото/аудио/голосовое) или нажмите /remove_file для удаления файла"
        )
        return EDIT_FILE

async def edit_datetime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    datetime_str = update.message.text
    dt = parse_datetime(datetime_str)
    
    if not dt:
        await update.message.reply_text("❌ Неверный формат! Используйте ДДММГГ ЧЧММ (например, 150624 1430)")
        return EDIT_DATETIME

    if dt < datetime.now():
        await update.message.reply_text("❌ Дата должна быть в будущем!")
        return EDIT_DATETIME

    event_id = context.user_data["edit_id"]

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE events SET datetime = ? WHERE id = ?",
            (format_datetime(dt), event_id),
        )

    await update.message.reply_text("✅ Дата события обновлена!")
    return ConversationHandler.END

async def edit_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_text = update.message.text
    event_id = context.user_data["edit_id"]

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE events SET event_text = ? WHERE id = ?",
            (new_text, event_id),
        )

    await update.message.reply_text("✅ Текст события обновлен!")
    return ConversationHandler.END

async def edit_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    event_id = context.user_data["edit_id"]
    file_id = file_type = file_name = None

    if update.message.document:
        file_id = update.message.document.file_id
        file_type = "document"
        file_name = update.message.document.file_name
    elif update.message.photo:
        file_id = update.message.photo[-1].file_id
        file_type = "photo"
    elif update.message.audio:
        file_id = update.message.audio.file_id
        file_type = "audio"
        file_name = update.message.audio.file_name
    elif update.message.voice:
        file_id = update.message.voice.file_id
        file_type = "voice"

    if file_id:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "UPDATE events SET file_id = ?, file_type = ?, file_name = ? WHERE id = ?",
                (file_id, file_type, file_name, event_id),
            )
        await update.message.reply_text("✅ Файл события обновлен!")
    else:
        await update.message.reply_text(
            "❌ Поддерживаются только документы, фото, аудио и голосовые сообщения"
        )
        return EDIT_FILE

    return ConversationHandler.END

async def remove_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    event_id = context.user_data["edit_id"]

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE events SET file_id = NULL, file_type = NULL, file_name = NULL WHERE id = ?",
            (event_id,),
        )

    await update.message.reply_text("✅ Файл удален из события!")
    return ConversationHandler.END

async def delete_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            "SELECT id, datetime, event_text FROM events WHERE user_id = ? ORDER BY datetime",
            (update.effective_user.id,),
        )
        events = cursor.fetchall()

    if not events:
        await update.message.reply_text("📭 Нет событий для удаления")
        return ConversationHandler.END

    message = "❌ Выберите событие для удаления (введите ID):\n\n"
    for event_id, dt, text in events:
        message += f"🆔 {event_id}\n⏰ {format_display_datetime(dt)}: {text[:50]}"
        if len(text) > 50:
            message += "..."
        message += "\n\n"

    await update.message.reply_text(message)
    return GET_EDIT_ID

async def confirm_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    event_id = context.user_data["edit_id"]

    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            "SELECT datetime, event_text FROM events WHERE id = ?", (event_id,)
        )
        dt, text = cursor.fetchone()

        keyboard = [
            [InlineKeyboardButton("✅ Да, удалить", callback_data=f"confirm_del_{event_id}")],
            [InlineKeyboardButton("❌ Нет, отменить", callback_data="cancel_del")]
        ]

        await update.message.reply_text(
            f"Вы уверены, что хотите удалить это событие?\n\n"
            f"🆔 {event_id}\n⏰ {format_display_datetime(dt)}: {text}",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    return ConversationHandler.END

async def handle_confirm_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data.startswith("confirm_del_"):
        event_id = int(query.data.split("_")[2])
        
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.execute(
                "SELECT datetime, event_text FROM events WHERE id = ?", (event_id,)
            )
            dt, text = cursor.fetchone()

            conn.execute("DELETE FROM events WHERE id = ?", (event_id,))
            conn.commit()

        await query.edit_message_text(
            text=f"🗑️ Событие удалено:\n⏰ {format_display_datetime(dt)}: {text}",
            reply_markup=None
        )
    else:
        await query.edit_message_text(
            text="❌ Удаление отменено",
            reply_markup=None
        )

async def handle_pagination(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    action = query.data

    if action == "prev_page":
        context.user_data["current_page"] -= 1
    elif action == "next_page":
        context.user_data["current_page"] += 1

    await show_events_page(update, context)

def main():
    init_db()

    app = Application.builder().token(TOKEN).build()

    conv_handler_add = ConversationHandler(
        entry_points=[CommandHandler("add", add_event)],
        states={
            GET_DATETIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_datetime)],
            GET_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_text)],
            GET_FILE: [
                MessageHandler(
                    filters.ATTACHMENT | filters.PHOTO | filters.AUDIO | filters.VOICE,
                    get_file_attachment,
                ),
                CommandHandler("skip", skip_file),
            ],
        },
        fallbacks=[],
    )

    conv_handler_file = ConversationHandler(
        entry_points=[
            CommandHandler("file", request_file),
            CallbackQueryHandler(handle_file_button, pattern="^get_files$"),
        ],
        states={
            GET_EVENT_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_event_id)]
        },
        fallbacks=[],
    )

    conv_handler_edit = ConversationHandler(
        entry_points=[CommandHandler("edit", edit_event)],
        states={
            GET_EDIT_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_edit_id)],
            EDIT_CHOICE: [CallbackQueryHandler(edit_choice, pattern="^edit_")],
            EDIT_DATETIME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_datetime)
            ],
            EDIT_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_text)],
            EDIT_FILE: [
                MessageHandler(
                    filters.ATTACHMENT | filters.PHOTO | filters.AUDIO | filters.VOICE,
                    edit_file,
                ),
                CommandHandler("remove_file", remove_file),
            ],
        },
        fallbacks=[],
    )

    conv_handler_delete = ConversationHandler(
        entry_points=[CommandHandler("delete", delete_event)],
        states={
            GET_EDIT_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_edit_id)],
            CONFIRM_DELETE: [CallbackQueryHandler(handle_confirm_delete, pattern="^(confirm_del_|cancel_del)")],
        },
        fallbacks=[],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("list", list_events))
    app.add_handler(CommandHandler("today", today_events))
    app.add_handler(conv_handler_add)
    app.add_handler(conv_handler_file)
    app.add_handler(conv_handler_edit)
    app.add_handler(conv_handler_delete)
    app.add_handler(CallbackQueryHandler(handle_pagination, pattern="^(prev_page|next_page)$"))

    app.run_polling()

if __name__ == "__main__":
    main()
