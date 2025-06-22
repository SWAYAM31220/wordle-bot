import random
import requests
import time
import os
import asyncio
from telegram import Update, constants
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
FIREBASE_URL = os.getenv("FIREBASE_URL")

with open("words.txt") as f:
    WORD_LIST = [w.strip().lower() for w in f if len(w.strip()) == 5]

ACTIVE_GAMES = {}

def get_game_data(chat_id):
    res = requests.get(f"{FIREBASE_URL}/games/{chat_id}.json")
    return res.json() or {}

def update_game_data(chat_id, data):
    requests.put(f"{FIREBASE_URL}/games/{chat_id}.json", json=data)

def end_game(chat_id):
    requests.delete(f"{FIREBASE_URL}/games/{chat_id}.json")
    ACTIVE_GAMES.pop(chat_id, None)

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

async def timeout_checker(chat_id, app):
    await asyncio.sleep(300)
    await app.bot.send_message(chat_id, "⏳ 5 minutes passed! Hurry up!")
    await asyncio.sleep(300)
    end_game(chat_id)
    await app.bot.send_message(chat_id, "❌ Time’s up! Game over. Use /quiz to start again.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🎮 *Guess the 5-Letter Word!*\n"
        "Type any 5-letter word to play.\n"
        "🟩 Correct letter & position\n"
        "🟨 Correct letter, wrong place\n"
        "🟥 Letter not in word\n\n"
        "🏆 Leaderboards, bonus points, hints, and more!\n"
        "🔧 Use /help for commands\n\n"
        "👨‍💻 *Made by* [LOST](https://t.me/confusedhomie)"
    )
    await update.message.reply_text(text, parse_mode="Markdown", disable_web_page_preview=True)

async def quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    word = random.choice(WORD_LIST)
    update_game_data(chat_id, {
        "current_word": word,
        "guessed": [],
        "attempts": {},
        "start_time": time.time()
    })
    ACTIVE_GAMES[chat_id] = True
    asyncio.create_task(timeout_checker(chat_id, context.application))
    await update.message.reply_text("🔁 New 5-letter word chosen! Start guessing!")

async def end(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    member = await chat.get_member(user.id)
    if member.status not in ["administrator", "creator"]:
        await update.message.reply_text("⛔ Only admins can end the game.")
        return
    end_game(str(chat.id))
    await update.message.reply_text("🚫 Game ended by admin.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "📘 *Available Commands:*\n"
        "/start - Show game intro and credits\n"
        "/quiz - Start a new 5-letter word\n"
        "/end - (Admin) End current game\n"
        "/hint - Get a hint (after 5 guesses)\n"
        "/ping - Check bot response time\n"
        "/global - Show global leaderboard\n"
        "/local - Show leaderboard of this group\n\n"
        "ℹ️ Guessing works *only* during an active game."
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    start = time.time()
    msg = await update.message.reply_text("🏓 Pong!")
    elapsed = int((time.time() - start) * 1000)
    await msg.edit_text(f"🏓 Pong! `{elapsed}ms`", parse_mode="Markdown")

async def hint(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    data = get_game_data(chat_id)
    guessed = data.get("guessed", [])
    word = data.get("current_word")

    if not word:
        await update.message.reply_text("🚫 No game running. Use /quiz to start.")
        return

    if len(guessed) < 5:
        await update.message.reply_text("❌ Hint only available after 5 guesses!")
        return

    revealed = f"🔍 Hint: One letter is `{random.choice(word)}`"
    await update.message.reply_text(revealed, parse_mode="Markdown")

async def global_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    data = get_leaderboard("global")
    sorted_scores = sorted(data.items(), key=lambda x: -x[1]["score"])[:10]
    msg = "🌍 *Global Leaderboard:*\n"
    your_score = data.get(uid, {}).get("score", 0)
    for i, (user_id, val) in enumerate(sorted_scores, 1):
        msg += f"{i}. {val['name']} — {val['score']} pt(s)\n"
    if uid not in [u[0] for u in sorted_scores]:
        all_sorted = sorted(data.items(), key=lambda x: -x[1]["score"])
        your_rank = [u[0] for u in all_sorted].index(uid) + 1
        msg += f"...\nYou: Rank {your_rank} — {your_score} pt(s)"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def local_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    uid = str(update.effective_user.id)
    data = get_leaderboard("local", chat_id)
    sorted_scores = sorted(data.items(), key=lambda x: -x[1]["score"])[:10]
    msg = "👥 *Group Leaderboard:*\n"
    your_score = data.get(uid, {}).get("score", 0)
    for i, (user_id, val) in enumerate(sorted_scores, 1):
        msg += f"{i}. {val['name']} — {val['score']} pt(s)\n"
    if uid not in [u[0] for u in sorted_scores]:
        all_sorted = sorted(data.items(), key=lambda x: -x[1]["score"])
        your_rank = [u[0] for u in all_sorted].index(uid) + 1
        msg += f"...\nYou: Rank {your_rank} — {your_score} pt(s)"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def handle_guess(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    uid = str(update.effective_user.id)
    name = update.effective_user.first_name
    guess = update.message.text.lower()

    if chat_id not in ACTIVE_GAMES:
        return

    if len(guess) != 5 or guess not in WORD_LIST:
        return

    data = get_game_data(chat_id)
    word = data.get("current_word")
    guessed = data.get("guessed", [])
    attempts = data.get("attempts", {})

    if not word:
        return

    if guess in guessed:
        await update.message.reply_text("⛔ Word already guessed!")
        return

    feedback = get_feedback(guess, word)
    await update.message.reply_text(f"{feedback} {guess.upper()}")

    guessed.append(guess)
    attempts.setdefault(uid, 0)
    attempts[uid] += 1

    if guess == word:
        await update.message.reply_text(f"🎉 Correct! The word was *{word.upper()}*", parse_mode="Markdown")
        meaning = get_word_meaning(word)
        await update.message.reply_text(f"📚 Meaning: {meaning}")
        bonus = attempts[uid] <= 3
        update_score(uid, name, chat_id, bonus=bonus)
        end_game(chat_id)
    else:
        update_game_data(chat_id, {
            "current_word": word,
            "guessed": guessed,
            "attempts": attempts
        })

app = ApplicationBuilder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("quiz", quiz))
app.add_handler(CommandHandler("end", end))
app.add_handler(CommandHandler("hint", hint))
app.add_handler(CommandHandler("help", help_command))
app.add_handler(CommandHandler("ping", ping))
app.add_handler(CommandHandler("global", global_leaderboard))
app.add_handler(CommandHandler("local", local_leaderboard))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_guess))

print("✅ WordleBot is live...")
app.run_polling()
