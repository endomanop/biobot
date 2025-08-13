import json
import re
import os
import logging
from datetime import datetime, timedelta
from telegram import Update, ChatPermissions
from telegram.ext import (
    ApplicationBuilder, CommandHandler,
    MessageHandler, ContextTypes, filters
)
from telegram.error import TelegramError
import asyncio
from aiohttp import web

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = 6216990986
DATA_FILE = "data.json"

# Load data or initialize empty dict
try:
    with open(DATA_FILE, "r") as f:
        db = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    db = {}

def save():
    with open(DATA_FILE, "w") as f:
        json.dump(db, f)

def is_link(text: str) -> bool:
    if not text:
        return False
    # Detect links or telegram handles in bio
    return bool(re.search(r"(https?://|www\.|t\.me/|telegram\.me/|@\w+)", text))

async def is_admin(update: Update, user_id: int) -> bool:
    try:
        member = await update.effective_chat.get_member(user_id)
        return member.status in ["administrator", "creator"]
    except TelegramError:
        return False

# Message handler: check user bio links, warn and mute
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or msg.chat.type == "private":
        return

    user = msg.from_user
    chat_id = str(msg.chat.id)
    uid = user.id

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
        await msg.delete()

        warns = db[chat_id]["warns"].get(str(uid), 0) + 1
        db[chat_id]["warns"][str(uid)] = warns
        save()

        if warns >= 3:
            until = datetime.utcnow() + timedelta(hours=1)
            await msg.chat.restrict_member(uid, ChatPermissions(can_send_messages=False), until_date=until)
            await msg.reply_html(f"🔇 {user.mention_html()} muted for 1 hour due to bio link (3 warnings).")
        else:
            await msg.reply_html(f"⚠️ {user.mention_html()} has link in bio. Warning {warns}/3")

# /allowbio command: add user to allowed list
async def allowbio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    user = update.effective_user
    if not await is_admin(update, user.id):
        await update.message.reply_text("❌ You must be admin to use this command.")
        return

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /allowbio <user_id>")
        return

    uid = int(context.args[0])
    db.setdefault(chat_id, {"allowed": [], "warns": {}, "groups": []})
    if uid not in db[chat_id]["allowed"]:
        db[chat_id]["allowed"].append(uid)
        save()
        await update.message.reply_text(f"✅ User {uid} allowed.")
    else:
        await update.message.reply_text("⚠️ User already allowed.")

# /delbio command: remove user from allowed list
async def delbio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    user = update.effective_user
    if not await is_admin(update, user.id):
        await update.message.reply_text("❌ You must be admin to use this command.")
        return

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /delbio <user_id>")
        return

    uid = int(context.args[0])
    if uid in db.get(chat_id, {}).get("allowed", []):
        db[chat_id]["allowed"].remove(uid)
        save()
        await update.message.reply_text(f"✅ User {uid} removed from allowed list.")
    else:
        await update.message.reply_text("⚠️ User not found in allowed list.")

# /broadcast command: owner only
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != OWNER_ID:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /broadcast <message>")
        return

    msg_text = " ".join(context.args)
    sent, failed = 0, 0

    for cid in db.keys():
        try:
            await context.bot.send_message(chat_id=int(cid), text=msg_text)
            sent += 1
        except Exception as e:
            logging.warning(f"Failed to send broadcast to {cid}: {e}")
            failed += 1

    await update.message.reply_text(f"📢 Broadcast sent to {sent} groups. Failed: {failed}")

# Track groups to db on any message
async def join_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    db.setdefault(chat_id, {"allowed": [], "warns": {}, "groups": []})
    save()

async def handle_healthcheck(request):
    return web.Response(text="OK")

async def start_http_server():
    app = web.Application()
    app.add_routes([web.get('/healthz', handle_healthcheck)])
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.getenv("PORT", "10000")))
    await site.start()
    print(f"HTTP server started on port {os.getenv('PORT', '10000')}")

async def main_async():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("allowbio", allowbio))
    app.add_handler(CommandHandler("delbio", delbio))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(MessageHandler(filters.ALL, join_group))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Start HTTP server and polling concurrently
    await asyncio.gather(
        start_http_server(),
        app.run_polling()
    )

def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    main()
