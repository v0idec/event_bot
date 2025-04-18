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
    CallbackQueryHandler
)

# --- Настройка ---
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DB_PATH = str(Path.home() / "telegram_bot_data" / "events.db")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Состояния ConversationHandler
GET_DATETIME, GET_TEXT, GET_FILE, GET_EVENT_ID = range(4)

# --- Инициализация БД ---
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            datetime TEXT NOT NULL,
            event_text TEXT NOT NULL,
            file_id TEXT,
            file_type TEXT,
            file_name TEXT
        )""")

# --- Обработчики команд ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📅 Бот для учета событий с файлами\n\n"
        "Доступные команды:\n"
        "/add - добавить событие\n"
        "/list - список событий\n"
        "/file - получить файл\n"
        "/delete - удалить событие"
    )

async def add_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📆 Введите дату и время события (ДД.ММ.ГГ ЧЧ:ММ):")
    return GET_DATETIME

async def get_datetime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        datetime_str = update.message.text
        dt = datetime.strptime(datetime_str, "%d.%m.%y %H:%M")
        context.user_data['datetime'] = datetime_str
        await update.message.reply_text("✏️ Введите описание события:")
        return GET_TEXT
    except ValueError:
        await update.message.reply_text("❌ Неверный формат! Используйте ДД.ММ.ГГ ЧЧ:ММ")
        return GET_DATETIME

async def get_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['text'] = update.message.text
    await update.message.reply_text(
        "📎 Прикрепите файл (документ/фото/аудио) или нажмите /skip"
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
    
    if file_id:
        await save_event(update, context, file_id, file_type, file_name)
    else:
        await update.message.reply_text("❌ Поддерживаются только документы, фото и аудио")
        return GET_FILE
    
    return ConversationHandler.END

async def skip_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await save_event(update, context)
    return ConversationHandler.END

async def save_event(update: Update, context: ContextTypes.DEFAULT_TYPE, 
                    file_id=None, file_type=None, file_name=None):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """INSERT INTO events 
            (user_id, datetime, event_text, file_id, file_type, file_name) 
            VALUES (?, ?, ?, ?, ?, ?)""",
            (
                update.effective_user.id,
                context.user_data['datetime'],
                context.user_data['text'],
                file_id,
                file_type,
                file_name
            )
        )
    msg = "✅ Событие сохранено!" + (" С файлом!" if file_id else "")
    await update.message.reply_text(msg)

async def list_events(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            """SELECT id, datetime, event_text, file_type, file_name 
            FROM events WHERE user_id = ? ORDER BY datetime""",
            (update.effective_user.id,)
        )
        events = cursor.fetchall()
    
    if not events:
        await update.message.reply_text("📭 Нет сохраненных событий")
        return
    
    message = "📋 Ваши события:\n\n"
    for event_id, dt, text, file_type, file_name in events:
        message += f"🆔 {event_id}\n⏰ {dt}: {text}\n"
        if file_type:
            name = file_name if file_name else file_type
            message += f"📎 Файл: {name}\n"
        message += "\n"
    
    keyboard = [[InlineKeyboardButton("📥 Скачать файлы", callback_data="get_files")]]
    
    await update.message.reply_text(
        message,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

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
                (event_id, update.effective_user.id)
            )
            file = cursor.fetchone()
        
        if not file:
            await update.message.reply_text("❌ Файл не найден")
            return ConversationHandler.END
        
        file_id, file_type, file_name = file
        caption = f"Файл из события {event_id}" if not file_name else file_name
        
        if file_type == 'document':
            await update.message.reply_document(
                document=file_id,
                caption=caption
            )
        elif file_type == 'photo':
            await update.message.reply_photo(
                photo=file_id,
                caption=caption
            )
        elif file_type == 'audio':
            await update.message.reply_audio(
                audio=file_id,
                caption=caption
            )
            
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

async def delete_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            "SELECT id, datetime, event_text FROM events WHERE user_id = ? ORDER BY datetime",
            (update.effective_user.id,)
        )
        events = cursor.fetchall()
    
    if not events:
        await update.message.reply_text("📭 Нет событий для удаления")
        return
    
    keyboard = [
        [InlineKeyboardButton(f"{dt}: {text[:20]}...", callback_data=f"del_{id}")]
        for id, dt, text in events
    ]
    
    await update.message.reply_text(
        "❌ Выберите событие для удаления:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def confirm_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    event_id = int(query.data.split('_')[1])
    
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            "SELECT datetime, event_text FROM events WHERE id = ?",
            (event_id,)
        )
        dt, text = cursor.fetchone()
        
        conn.execute("DELETE FROM events WHERE id = ?", (event_id,))
        conn.commit()
    
    await query.edit_message_text(
        text=f"🗑️ Событие удалено:\n⏰ {dt}: {text}",
        reply_markup=None
    )

# --- Запуск приложения ---
def main():
    init_db()
    
    app = Application.builder().token(TOKEN).build()
    
    # Обработчики команд
    conv_handler_add = ConversationHandler(
        entry_points=[CommandHandler('add', add_event)],
        states={
            GET_DATETIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_datetime)],
            GET_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_text)],
            GET_FILE: [
                MessageHandler(
                    filters.ATTACHMENT | filters.PHOTO | filters.AUDIO,
                    get_file_attachment
                ),
                CommandHandler('skip', skip_file)
            ],
        },
        fallbacks=[]
    )
    
    conv_handler_file = ConversationHandler(
        entry_points=[
            CommandHandler('file', request_file),
            CallbackQueryHandler(handle_file_button, pattern="^get_files$")
        ],
        states={
            GET_EVENT_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_event_id)]
        },
        fallbacks=[]
    )
    
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('list', list_events))
    app.add_handler(CommandHandler('delete', delete_event))
    app.add_handler(conv_handler_add)
    app.add_handler(conv_handler_file)
    app.add_handler(CallbackQueryHandler(confirm_delete, pattern='^del_'))
    
    app.run_polling()

if __name__ == '__main__':
    main()
