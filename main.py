import json, re, os, sys, logging, asyncio
from datetime import datetime, timedelta
from telegram import Update, ChatPermissions
from telegram.ext import (
    ApplicationBuilder, CommandHandler,
    MessageHandler, ContextTypes, filters
)
from telegram.error import TelegramError

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = 6216990986
DATA_FILE = "data.json"

# Load data
try:
    with open(DATA_FILE, "r") as f:
        db = json.load(f)
except:
    db = {}

def save():
    with open(DATA_FILE, "w") as f:
        json.dump(db, f)

def is_link(text: str):
    if not text: return False
    return bool(re.search(r"(https?://|www\.|t\.me/|telegram\.me/|@\w+)", text))

async def is_admin(update: Update, user_id: int):
    try:
        member = await update.effective_chat.get_member(user_id)
        return member.status in ["administrator", "creator"]
    except:
        return False

# ========== Message Handler ========== #
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user = msg.from_user
    chat_id = str(msg.chat.id)
    uid = user.id

    if not msg or msg.chat.type == "private":
        return

    if await is_admin(update, uid):
        return

    db.setdefault(chat_id, {"allowed": [], "warns": {}, "groups": []})
    if uid in db[chat_id]["allowed"]:
        return

    try:
        user_chat = await context.bot.get_chat(uid)
        bio = getattr(user_chat, "bio", "")
    except TelegramError:
        return

    if is_link(bio):
        # Bio has link
        await msg.delete()

        warns = db[chat_id]["warns"].get(str(uid), 0) + 1
        db[chat_id]["warns"][str(uid)] = warns
        save()

        if warns >= 3:
            until = datetime.utcnow() + timedelta(hours=1)
            await msg.chat.restrict_member(uid, ChatPermissions(can_send_messages=False), until_date=until)
            await msg.reply_text(f"🔇 {user.mention_html()} muted for 1 hour due to bio link (3 warnings).", parse_mode="HTML")
        else:
            await msg.reply_text(f"⚠️ {user.mention_html()} has link in bio. Warning {warns}/3", parse_mode="HTML")

# ========== Commands ========== #
async def allowbio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    user = update.effective_user
    if not await is_admin(update, user.id):
        return

    if not context.args or not context.args[0].isdigit():
        return await update.message.reply_text("Usage: /allowbio <user_id>")

    uid = int(context.args[0])
    db.setdefault(chat_id, {"allowed": [], "warns": {}, "groups": []})
    if uid not in db[chat_id]["allowed"]:
        db[chat_id]["allowed"].append(uid)
        save()
        await update.message.reply_text(f"✅ User {uid} allowed.")
    else:
        await update.message.reply_text("⚠️ Already allowed.")

async def delbio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    user = update.effective_user
    if not await is_admin(update, user.id):
        return

    if not context.args or not context.args[0].isdigit():
        return await update.message.reply_text("Usage: /delbio <user_id>")

    uid = int(context.args[0])
    if uid in db.get(chat_id, {}).get("allowed", []):
        db[chat_id]["allowed"].remove(uid)
        save()
        await update.message.reply_text(f"✅ User {uid} removed.")
    else:
        await update.message.reply_text("⚠️ User not in allowed list.")

# Broadcast command (owner only)
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != OWNER_ID:
        return

    if not context.args:
        return await update.message.reply_text("Usage: /broadcast <message>")

    msg_text = " ".join(context.args)
    sent, failed = 0, 0

    chats = list(db.keys())
    for cid in chats:
        try:
            await context.bot.send_message(chat_id=int(cid), text=msg_text)
            sent += 1
        except:
            failed += 1

    await update.message.reply_text(f"📢 Broadcast sent to {sent} groups. Failed: {failed}")

# Track groups
async def join_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    db.setdefault(chat_id, {"allowed": [], "warns": {}, "groups": []})
    save()

# ========== Main ========== #
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("allowbio", allowbio))
    app.add_handler(CommandHandler("delbio", delbio))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(MessageHandler(filters.ALL, join_group))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.run_polling()

if __name__ == "__main__":
    main()
