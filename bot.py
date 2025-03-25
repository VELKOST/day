import telebot
from telebot import types
import sqlite3
import random
import os
from dotenv import load_dotenv
from types import SimpleNamespace
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime

load_dotenv()

API_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

bot = telebot.TeleBot(API_TOKEN)

# --- База данных
conn = sqlite3.connect('phrases.db', check_same_thread=False)
cursor = conn.cursor()

cursor.execute('''
CREATE TABLE IF NOT EXISTS phrases (
    id INTEGER PRIMARY KEY,
    text TEXT,
    approved INTEGER DEFAULT 1
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS suggestions (
    id INTEGER PRIMARY KEY,
    user_id INTEGER,
    text TEXT
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS subscribers (
    user_id INTEGER PRIMARY KEY
)
''')
conn.commit()


# --- Клавиатура
def main_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("📝 Новая фраза")
    return markup


# --- /start
@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(
        message.chat.id,
        "Привет! Жми кнопку ниже, чтобы получить фразу дня.",
        reply_markup=main_keyboard()
    )


# --- Кнопка "📝 Новая фраза"
@bot.message_handler(func=lambda message: message.text == "📝 Новая фраза")
def handle_new_phrase_button(message):
    send_phrase(SimpleNamespace(message=message))


# --- Фраза
def send_phrase(target):
    cursor.execute("SELECT text FROM phrases WHERE approved = 1")
    results = cursor.fetchall()
    if results:
        phrase = random.choice(results)[0]
        bot.send_message(target.message.chat.id, f"✨ Фраза дня:\n\n{phrase}", reply_markup=main_keyboard())
    else:
        bot.send_message(target.message.chat.id, "Пока нет одобренных фраз 😔", reply_markup=main_keyboard())


@bot.message_handler(commands=['newphrase'])
def cmd_newphrase(message):
    send_phrase(SimpleNamespace(message=message))


# --- Подписка
@bot.message_handler(commands=['subscribe'])
def subscribe(message):
    cursor.execute("INSERT OR IGNORE INTO subscribers (user_id) VALUES (?)", (message.chat.id,))
    conn.commit()
    bot.send_message(message.chat.id, "✅ Вы подписались на ежедневную мотивацию!")


@bot.message_handler(commands=['unsubscribe'])
def unsubscribe(message):
    cursor.execute("DELETE FROM subscribers WHERE user_id = ?", (message.chat.id,))
    conn.commit()
    bot.send_message(message.chat.id, "❌ Вы отписались от ежедневных фраз.")


# --- Ежедневная рассылка
def send_daily_phrases():
    cursor.execute("SELECT text FROM phrases WHERE approved = 1")
    phrases = cursor.fetchall()
    if not phrases:
        return
    phrase = random.choice(phrases)[0]

    cursor.execute("SELECT user_id FROM subscribers")
    users = cursor.fetchall()

    for (user_id,) in users:
        try:
            bot.send_message(user_id, f"🌞 Фраза дня:\n\n{phrase}", reply_markup=main_keyboard())
        except Exception as e:
            print(f"Ошибка отправки {user_id}: {e}")


scheduler = BackgroundScheduler()
scheduler.add_job(send_daily_phrases, 'cron', hour=12, minute=0)
scheduler.start()


# --- Предложение фразы
@bot.message_handler(commands=['suggest'])
def suggest_phrase(message):
    msg = bot.send_message(message.chat.id, "Напиши свою фразу дня:")
    bot.register_next_step_handler(msg, save_suggestion)


def save_suggestion(message):
    cursor.execute("INSERT INTO suggestions (user_id, text) VALUES (?, ?)", (message.from_user.id, message.text))
    conn.commit()
    bot.send_message(message.chat.id, "Спасибо! Фраза отправлена на модерацию.")


# --- Модерация
@bot.message_handler(commands=['moderate'])
def moderate(message):
    if message.from_user.id != ADMIN_ID:
        return bot.send_message(message.chat.id, "У тебя нет доступа к этой команде.")
    cursor.execute("SELECT id, text FROM suggestions")
    suggestions = cursor.fetchall()
    if not suggestions:
        return bot.send_message(message.chat.id, "Нет предложенных фраз.")

    for sid, text in suggestions:
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("✅ Одобрить", callback_data=f"approve_{sid}"),
            types.InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{sid}")
        )
        bot.send_message(message.chat.id, f"Предложение:\n{text}", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith("approve_") or call.data.startswith("reject_"))
def handle_moderation(call):
    if call.from_user.id != ADMIN_ID:
        return bot.answer_callback_query(call.id, "Не для тебя 😎")

    action, sid = call.data.split("_")
    sid = int(sid)

    cursor.execute("SELECT text FROM suggestions WHERE id = ?", (sid,))
    result = cursor.fetchone()
    if not result:
        return bot.edit_message_text("Фраза уже обработана.", call.message.chat.id, call.message.message_id)

    text = result[0]

    if action == "approve":
        cursor.execute("INSERT INTO phrases (text, approved) VALUES (?, 1)", (text,))
        conn.commit()
        bot.edit_message_text(f"✅ Одобрено:\n{text}", call.message.chat.id, call.message.message_id)
    else:
        bot.edit_message_text(f"❌ Отклонено:\n{text}", call.message.chat.id, call.message.message_id)

    cursor.execute("DELETE FROM suggestions WHERE id = ?", (sid,))
    conn.commit()


# --- Пакетная загрузка фраз
@bot.message_handler(commands=['bulkadd'])
def bulk_add(message):
    if message.from_user.id != ADMIN_ID:
        return bot.send_message(message.chat.id, "Доступ только для администратора.")
    msg = bot.send_message(message.chat.id, "Отправь список фраз (по одной на строку):")
    bot.register_next_step_handler(msg, save_bulk)


def save_bulk(message):
    phrases = message.text.strip().split("\n")
    count = 0
    for phrase in phrases:
        clean = phrase.strip()
        if clean:
            cursor.execute("INSERT INTO phrases (text, approved) VALUES (?, 1)", (clean,))
            count += 1
    conn.commit()
    bot.send_message(message.chat.id, f"✅ Загружено {count} фраз.")


# --- Запуск
print("Бот запущен...")
bot.infinity_polling()
