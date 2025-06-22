import os
import random
import requests
import time
import asyncio
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters
)
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
FIREBASE_URL = os.getenv("FIREBASE_URL")

with open("words.txt") as f:
    WORD_LIST = [w.strip().lower() for w in f if len(w.strip()) == 5]

active_games = {}

# === Firebase Helper Functions ===

def get_game_data(chat_id):
    res = requests.get(f"{FIREBASE_URL}/games/{chat_id}.json")
    return res.json() or {}

def update_game_data(chat_id, data):
    requests.put(f"{FIREBASE_URL}/games/{chat_id}.json", json=data)

def end_game(chat_id):
    requests.delete(f"{FIREBASE_URL}/games/{chat_id}.json")

def update_score(user_id, name, chat_id=None, bonus=False):
    paths = [f"{FIREBASE_URL}/scores/global/{user_id}.json"]
    if chat_id:
        paths.append(f"{FIREBASE_URL}/scores/local/{chat_id}/{user_id}.json")

    for path in paths:
        current = requests.get(path).json() or {"score": 0, "name": name}
        current["score"] += 2 if bonus else 1
        requests.put(path, json=current)

def get_leaderboard(scope, chat_id=None):
    if scope == "global":
        res = requests.get(f"{FIREBASE_URL}/scores/global.json")
    else:
        res = requests.get(f"{FIREBASE_URL}/scores/local/{chat_id}.json")
    return res.json() or {}

def get_word_meaning(word):
    res = requests.get(f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}")
    if res.status_code == 200:
        try:
            return res.json()[0]['meanings'][0]['definitions'][0]['definition']
        except:
            return "No meaning found."
    return "No meaning found."

def get_feedback(guess, actual):
    feedback = []
    for i in range(5):
        if guess[i] == actual[i]:
            feedback.append("🟩")
        elif guess[i] in actual:
            feedback.append("🟨")
        else:
            feedback.append("🟥")
    return ''.join(feedback)

# === Bot Handlers ===

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "\n🎮 Guess the 5-Letter Word!\n"
        "Type any 5-letter word to play.\n"
        "🟩 Correct letter & position\n"
        "🟨 Correct letter, wrong place\n"
        "🟥 Letter not in word\n\n"
        "⏱ 10-min timeout per round (5-min warning)\n"
        "🏆 Leaderboards, bonus points, hints & more!\n\n"
        "Commands:\n"
        "/quiz - Start new game\n"
        "/hint - Hint after 5 tries\n"
        "/end - Admin ends game\n"
        "/global - Global leaderboard\n"
        "/local - Group leaderboard\n"
        "/ping - Check latency\n"
        "/help - See this again\n\n"
        "👨‍💻 Made by LOST"
    )
    await update.message.reply_text(text, parse_mode="Markdown", disable_web_page_preview=True)

async def quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    word = random.choice(WORD_LIST)
    data = {
        "current_word": word,
        "guessed": [],
        "attempts": {},
        "start_time": time.time()
    }
    update_game_data(chat_id, data)
    active_games[chat_id] = data
    await update.message.reply_text("🧠 New word chosen! Start guessing!")
    context.application.create_task(schedule_timeout(context, chat_id))

async def schedule_timeout(context, chat_id):
    await asyncio.sleep(300)
    await context.bot.send_message(chat_id=chat_id, text="⚠️ 5 minutes left!")
    await asyncio.sleep(300)
    end_game(chat_id)
    await context.bot.send_message(chat_id=chat_id, text="⌛ Time's up! Game ended.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    start_time = time.time()
    msg = await update.message.reply_text("🏓 Pong!")
    elapsed = int((time.time() - start_time) * 1000)
    await msg.edit_text(f"🏓 Pong! {elapsed}ms", parse_mode="Markdown")

async def hint(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    data = get_game_data(chat_id)
    if not data.get("current_word"):
        await update.message.reply_text("❌ No active game. Use /quiz to start one.")
        return
    if len(data.get("guessed", [])) < 5:
        await update.message.reply_text("🔒 Hint only after 5 guesses!")
        return
    await update.message.reply_text(f"🔍 One letter: {random.choice(data['current_word'])}", parse_mode="Markdown")

async def end(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    member = await chat.get_member(user.id)
    if member.status not in ["administrator", "creator"]:
        await update.message.reply_text("⛔ Only admins can end the game.")
        return
    end_game(str(chat.id))
    await update.message.reply_text("🛑 Game ended by admin.")

async def global_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = get_leaderboard("global")
    sorted_scores = sorted(data.items(), key=lambda x: -x[1]["score"])[:10]
    msg = "🌍 Global Leaderboard:\n"
    for i, (uid, val) in enumerate(sorted_scores, 1):
        msg += f"{i}. {val['name']} — {val['score']} pts\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def local_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    data = get_leaderboard("local", chat_id)
    sorted_scores = sorted(data.items(), key=lambda x: -x[1]["score"])[:10]
    msg = "👥 Group Leaderboard:\n"
    for i, (uid, val) in enumerate(sorted_scores, 1):
        msg += f"{i}. {val['name']} — {val['score']} pts\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def handle_guess(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    uid = str(update.effective_user.id)
    name = update.effective_user.first_name
    guess = update.message.text.lower()

    data = get_game_data(chat_id)
    word = data.get("current_word")
    if not word or len(guess) != 5 or guess not in WORD_LIST or guess in data.get("guessed", []):
        return

    feedback = get_feedback(guess, word)
    await update.message.reply_text(f"{feedback} {guess.upper()}")

    data["guessed"].append(guess)
    data["attempts"][uid] = data["attempts"].get(uid, 0) + 1

    if guess == word:
        await update.message.reply_text(f"🎉 Correct! The word was *{word.upper()}*", parse_mode="Markdown")
        await update.message.reply_text(f"📚 Meaning: {get_word_meaning(word)}")
        update_score(uid, name, chat_id, bonus=(data["attempts"][uid] <= 3))
        end_game(chat_id)
    else:
        update_game_data(chat_id, data)

# === Main ===

if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("quiz", quiz))
    app.add_handler(CommandHandler("hint", hint))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CommandHandler("end", end))
    app.add_handler(CommandHandler("global", global_leaderboard))
    app.add_handler(CommandHandler("local", local_leaderboard))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_guess))

    print("✅ WordleBot running...")
    app.run_polling()
