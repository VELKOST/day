import telebot
from telebot import types
import sqlite3
import random
import os
from dotenv import load_dotenv
load_dotenv()
from types import SimpleNamespace


API_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

bot = telebot.TeleBot(API_TOKEN)

# База данных
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
conn.commit()


@bot.message_handler(commands=['start'])
def start(message):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📝 Новая фраза", callback_data='new_phrase'))
    bot.send_message(message.chat.id, "Привет! Жми кнопку, чтобы получить фразу дня.", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data == 'new_phrase')
def send_phrase(call):
    cursor.execute("SELECT text FROM phrases WHERE approved = 1")
    results = cursor.fetchall()
    if results:
        phrase = random.choice(results)[0]
        bot.send_message(call.message.chat.id, f"✨ Фраза дня:\n\n{phrase}")
    else:
        bot.send_message(call.message.chat.id, "Пока нет одобренных фраз 😔")


@bot.message_handler(commands=['newphrase'])
def cmd_newphrase(message):
    send_phrase(SimpleNamespace(message=message))



@bot.message_handler(commands=['suggest'])
def suggest_phrase(message):
    msg = bot.send_message(message.chat.id, "Напиши свою фразу дня:")
    bot.register_next_step_handler(msg, save_suggestion)


def save_suggestion(message):
    cursor.execute("INSERT INTO suggestions (user_id, text) VALUES (?, ?)", (message.from_user.id, message.text))
    conn.commit()
    bot.send_message(message.chat.id, "Спасибо! Фраза отправлена на модерацию.")


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


print("Бот запущен...")
bot.infinity_polling()
