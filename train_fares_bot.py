#!/usr/bin/env python3
"""
Train Fares Telegram Bot - Sends train fare updates on Wednesdays and Saturdays at 3pm

Usage:
    python train_fares_bot.py           - Run bot for interactive commands (/start, /stop, /check)
    python train_fares_bot.py scheduled - Send fares to all subscribers and exit (for cron)
"""

import asyncio
import json
import os
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes

from train_fares import main as fetch_train_fares

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot configuration
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_IDS_FILE = Path(__file__).parent / "chat_ids..json"


def load_chat_ids() -> list[int]:
    """Load chat IDs from JSON file."""
    if not CHAT_IDS_FILE.exists():
        return []
    
    try:
        with open(CHAT_IDS_FILE, "r") as f:
            data = json.load(f)
            return data.get("chat_ids", [])
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Error loading chat IDs: {e}")
        return []


def save_chat_ids(chat_ids: list[int]) -> None:
    """Save chat IDs to JSON file."""
    try:
        with open(CHAT_IDS_FILE, "w") as f:
            json.dump({"chat_ids": chat_ids}, f, indent=2)
    except IOError as e:
        logger.error(f"Error saving chat IDs: {e}")


def add_chat_id(chat_id: int) -> bool:
    """Add a chat ID to the list. Returns True if newly added."""
    chat_ids = load_chat_ids()
    if chat_id not in chat_ids:
        chat_ids.append(chat_id)
        save_chat_ids(chat_ids)
        return True
    return False


def remove_chat_id(chat_id: int) -> bool:
    """Remove a chat ID from the list. Returns True if removed."""
    chat_ids = load_chat_ids()
    if chat_id in chat_ids:
        chat_ids.remove(chat_id)
        save_chat_ids(chat_ids)
        return True
    return False


async def send_scheduled_fares() -> None:
    """Send train fares to all subscribers (called by cron)."""
    if not BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable is required")
    
    chat_ids = load_chat_ids()
    
    if not chat_ids:
        logger.info("No subscribers to send train fares to")
        return
    
    logger.info(f"Fetching train fares for {len(chat_ids)} subscribers...")
    
    bot = Bot(token=BOT_TOKEN)
    
    try:
        message = fetch_train_fares()
        
        async with bot:
            for chat_id in chat_ids:
                try:
                    await bot.send_message(
                        chat_id=chat_id,
                        text=message,
                        parse_mode="Markdown"
                    )
                    logger.info(f"Sent to chat {chat_id}")
                except Exception as e:
                    logger.error(f"Error sending to chat {chat_id}: {e}")
        
        logger.info("Train fares sent successfully")
    except Exception as e:
        logger.error(f"Error fetching train fares: {e}")
        raise


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command - subscribes user and shows bot info."""
    chat_id = update.effective_chat.id
    is_new = add_chat_id(chat_id)
    
    if is_new:
        await update.message.reply_text(
            "🚂 *Train Fares Bot*\n\n"
            "Welcome! You're now subscribed to GWR train fare updates.\n\n"
            "You'll receive updates on *Wednesdays* and *Saturdays* at *3pm*.\n\n"
            "Commands:\n"
            "/check - Get fares now\n"
            "/stop - Unsubscribe",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            "🚂 *Train Fares Bot*\n\n"
            "You're already subscribed!\n\n"
            "Commands:\n"
            "/check - Get fares now\n"
            "/stop - Unsubscribe",
            parse_mode="Markdown"
        )


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /stop command - unsubscribe from updates."""
    chat_id = update.effective_chat.id
    was_subscribed = remove_chat_id(chat_id)
    
    if was_subscribed:
        await update.message.reply_text(
            "👋 You've been unsubscribed from train fare updates.\n\n"
            "Use /start to subscribe again.",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            "You weren't subscribed. Use /start to subscribe.",
            parse_mode="Markdown"
        )


async def check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /check command - manually trigger a fare check."""
    await update.message.reply_text("🔍 Fetching train fares...")
    
    try:
        message = fetch_train_fares()
        await update.message.reply_text(message, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in /check command: {e}")
        await update.message.reply_text(f"❌ Error fetching fares: {e}")


def run_bot() -> None:
    """Run the bot in polling mode for interactive commands."""
    if not BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable is required")
    
    # Create the Application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stop", stop))
    application.add_handler(CommandHandler("check", check))
    
    # Start the bot
    logger.info("Starting bot in polling mode...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


def main() -> None:
    """Main entry point."""
    if len(sys.argv) > 1 and sys.argv[1] == "scheduled":
        # Cron mode: send fares and exit
        logger.info("Running in scheduled mode...")
        asyncio.run(send_scheduled_fares())
    else:
        # Interactive mode: run bot for commands
        run_bot()


if __name__ == "__main__":
    main()
