#!/usr/bin/env python3
"""
Train Fares Telegram Bot - Sends train fare updates based on user preferences

Usage:
    python train_fares_bot.py           - Run bot for interactive commands
    python train_fares_bot.py scheduled - Check for scheduled messages and send fares
"""

import asyncio
import json
import os
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from rapidfuzz import fuzz, process
from telegram import Bot, Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

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
CHECK_COOLDOWN_HOURS = int(os.environ.get("CHECK_COOLDOWN_HOURS", "4"))
FUZZY_SEARCH_THRESHOLD = int(os.environ.get("FUZZY_SEARCH_THRESHOLD", "90"))
CHAT_IDS_FILE = Path(__file__).parent / "chat_ids..json"
LOCATIONS_FILE = Path(__file__).parent / "locations.json"

# Conversation states
(
    START_STATION,
    SELECT_START_STATION,
    OUTBOUND_DAY,
    OUTBOUND_TIME,
    RETURN_STATION,
    SELECT_RETURN_STATION,
    RETURN_DAY,
    RETURN_TIME,
    MESSAGE_DAYS,
    MESSAGE_TIME,
    OUTBOUND_THRESHOLD,
    RETURN_THRESHOLD,
    PERIOD_IN_MONTHS,
    # Change settings states
    CHANGE_MENU,
    CHANGE_START_STATION,
    CHANGE_SELECT_START_STATION,
    CHANGE_RETURN_STATION,
    CHANGE_SELECT_RETURN_STATION,
    CHANGE_OUTBOUND_DAY,
    CHANGE_OUTBOUND_TIME,
    CHANGE_RETURN_DAY,
    CHANGE_RETURN_TIME,
    CHANGE_OUTBOUND_THRESHOLD,
    CHANGE_RETURN_THRESHOLD,
    CHANGE_MESSAGE_DAYS,
    CHANGE_MESSAGE_DAYS_SECOND,
    CHANGE_MESSAGE_TIME,
    CHANGE_PERIOD,
) = range(28)

# Day options
DAYS_OF_WEEK = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# Time slots (00:00 to 23:45 in 15-minute increments)
TIME_SLOTS = [f"{h:02d}:{m:02d}" for h in range(24) for m in (0, 15, 30, 45)]

# Period options (months to look ahead)
PERIOD_OPTIONS = [1, 2, 3]


def get_time_keyboard() -> ReplyKeyboardMarkup:
    """Create a keyboard with time slots in rows of 4."""
    # Group times into rows of 4 for better display
    rows = [TIME_SLOTS[i:i + 4] for i in range(0, len(TIME_SLOTS), 4)]
    return ReplyKeyboardMarkup(rows, one_time_keyboard=True, resize_keyboard=True)


def get_day_keyboard(exclude: list[str] | None = None) -> ReplyKeyboardMarkup:
    """Create a keyboard with days of the week."""
    exclude = exclude or []
    days = [d for d in DAYS_OF_WEEK if d not in exclude]
    keyboard = [[day] for day in days]
    return ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)


def get_period_keyboard() -> ReplyKeyboardMarkup:
    """Create a keyboard with period options (months)."""
    keyboard = [[f"{months} month{'s' if months > 1 else ''}"] for months in PERIOD_OPTIONS]
    return ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)


def load_locations() -> list[dict]:
    """Load station locations from JSON file."""
    try:
        with open(LOCATIONS_FILE, "r") as f:
            data = json.load(f)
            return data.get("data", [])
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Error loading locations: {e}")
        return []


def search_stations(query: str, locations: list[dict], limit: int = 3) -> list[dict]:
    """Search for stations matching the query using fuzzy matching.
    
    Returns up to `limit` matches. If only one result scores above FUZZY_SEARCH_THRESHOLD,
    only that result is returned.
    """
    # Build list of station names for fuzzy matching
    station_names = [loc.get("name", "") for loc in locations]
    
    # Use rapidfuzz to find best matches
    # score_cutoff of 60 allows for typos while filtering out poor matches
    results = process.extract(
        query,
        station_names,
        scorer=fuzz.WRatio,
        limit=limit,
        score_cutoff=60
    )
    
    if not results:
        return []
    
    matches = []
    for name, score, index in results:
        loc = locations[index]
        matches.append({
            "name": loc.get("name", ""),
            "code": loc.get("code", ""),
            "nlc": loc.get("nlc", ""),
            "score": score
        })
    
    # If the top result has a very high score, only return that one
    if matches and matches[0]["score"] >= FUZZY_SEARCH_THRESHOLD:
        return [matches[0]]
    
    return matches


def load_user_data() -> dict:
    """Load all user data from JSON file."""
    if not CHAT_IDS_FILE.exists():
        return {"users": {}}
    
    try:
        with open(CHAT_IDS_FILE, "r") as f:
            data = json.load(f)
            # Handle old format migration
            if "chat_ids" in data and "users" not in data:
                return {"users": {}}
            return data
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Error loading user data: {e}")
        return {"users": {}}


def save_user_data(data: dict) -> None:
    """Save user data to JSON file."""
    try:
        with open(CHAT_IDS_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except IOError as e:
        logger.error(f"Error saving user data: {e}")


def get_user_preferences(chat_id: int) -> dict | None:
    """Get preferences for a specific user."""
    data = load_user_data()
    return data.get("users", {}).get(str(chat_id))


def save_user_preferences(chat_id: int, preferences: dict) -> None:
    """Save preferences for a specific user."""
    data = load_user_data()
    if "users" not in data:
        data["users"] = {}
    data["users"][str(chat_id)] = preferences
    save_user_data(data)


def remove_user(chat_id: int) -> bool:
    """Remove a user from the data. Returns True if removed."""
    data = load_user_data()
    if str(chat_id) in data.get("users", {}):
        del data["users"][str(chat_id)]
        save_user_data(data)
        return True
    return False


def get_users_for_scheduled_time(current_time: datetime, tolerance_minutes: int = 5) -> list[tuple[int, dict]]:
    """Get users who should receive a message at the current time."""
    data = load_user_data()
    current_day = DAYS_OF_WEEK[current_time.weekday()]
    current_minutes = current_time.hour * 60 + current_time.minute
    
    matching_users = []
    
    for chat_id_str, prefs in data.get("users", {}).items():
        message_days = prefs.get("message_days", [])
        message_time = prefs.get("message_time", "")
        
        if current_day not in message_days:
            continue
        
        if not message_time:
            continue
        
        try:
            hour, minute = map(int, message_time.split(":"))
            pref_minutes = hour * 60 + minute
            
            if abs(current_minutes - pref_minutes) <= tolerance_minutes:
                matching_users.append((int(chat_id_str), prefs))
        except ValueError:
            continue
    
    return matching_users


# ============== Conversation Handlers ==============

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the setup conversation."""
    await update.message.reply_text(
        "🚂 *Train Fares Bot Setup*\n\n"
        "I'll help you set up personalized train fare alerts!\n\n"
        "First, let's set up your *outbound journey*.\n\n"
        "Please type the name of your *departure station*\n"
        "(e.g., 'Swansea' or 'London Paddington'):",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )
    
    # Load locations into context for later use
    context.user_data["locations"] = load_locations()
    context.user_data["preferences"] = {}
    
    return START_STATION


async def start_station_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Search for the start station."""
    query = update.message.text.strip()
    locations = context.user_data.get("locations", [])
    
    matches = search_stations(query, locations)
    
    if not matches:
        await update.message.reply_text(
            f"❌ No stations found matching '{query}'.\n\n"
            "Please try again with a different search term:"
        )
        return START_STATION
    
    context.user_data["station_matches"] = matches
    
    # Create keyboard with matches
    keyboard = [[m["name"]] for m in matches]
    keyboard.append(["🔍 Search again"])
    
    await update.message.reply_text(
        f"Found {len(matches)} station(s) matching '{query}'.\n\n"
        "Please select your *departure station*:",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    
    return SELECT_START_STATION


async def select_start_station(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle start station selection."""
    selection = update.message.text.strip()
    
    if selection == "🔍 Search again":
        await update.message.reply_text(
            "Please type the name of your *departure station*:",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove()
        )
        return START_STATION
    
    matches = context.user_data.get("station_matches", [])
    selected = next((m for m in matches if m["name"] == selection), None)
    
    if not selected:
        await update.message.reply_text(
            "Please select a station from the list or search again.",
            reply_markup=ReplyKeyboardRemove()
        )
        return START_STATION
    
    context.user_data["preferences"]["start_station_name"] = selected["name"]
    context.user_data["preferences"]["start_station_code"] = selected["nlc"]
    
    # Ask for outbound day
    await update.message.reply_text(
        f"✅ Departure station: *{selected['name']}*\n\n"
        "Which day of the week do you usually *leave* this station?",
        parse_mode="Markdown",
        reply_markup=get_day_keyboard()
    )
    
    return OUTBOUND_DAY


async def outbound_day(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle outbound day selection."""
    day = update.message.text.strip()
    
    if day not in DAYS_OF_WEEK:
        await update.message.reply_text(
            "Please select a day from the list:",
            reply_markup=get_day_keyboard()
        )
        return OUTBOUND_DAY
    
    context.user_data["preferences"]["outbound_day"] = day
    
    await update.message.reply_text(
        f"✅ Outbound day: *{day}*\n\n"
        "What time do you usually depart?",
        parse_mode="Markdown",
        reply_markup=get_time_keyboard()
    )
    
    return OUTBOUND_TIME


async def outbound_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle outbound time selection."""
    time_str = update.message.text.strip()
    
    if time_str not in TIME_SLOTS:
        await update.message.reply_text(
            "Please select a time from the list:",
            reply_markup=get_time_keyboard()
        )
        return OUTBOUND_TIME
    
    context.user_data["preferences"]["outbound_time"] = time_str
    
    await update.message.reply_text(
        f"✅ Outbound time: *{time_str}*\n\n"
        "Now let's set up your *return journey*.\n\n"
        "Please type the name of your *return station*\n"
        "(where you'll be coming back from):",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )
    
    return RETURN_STATION


async def return_station_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Search for the return station."""
    query = update.message.text.strip()
    locations = context.user_data.get("locations", [])
    
    matches = search_stations(query, locations)
    
    if not matches:
        await update.message.reply_text(
            f"❌ No stations found matching '{query}'.\n\n"
            "Please try again with a different search term:"
        )
        return RETURN_STATION
    
    context.user_data["station_matches"] = matches
    
    keyboard = [[m["name"]] for m in matches]
    keyboard.append(["🔍 Search again"])
    
    await update.message.reply_text(
        f"Found {len(matches)} station(s) matching '{query}'.\n\n"
        "Please select your *return station*:",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    
    return SELECT_RETURN_STATION


async def select_return_station(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle return station selection."""
    selection = update.message.text.strip()
    
    if selection == "🔍 Search again":
        await update.message.reply_text(
            "Please type the name of your *return station*:",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove()
        )
        return RETURN_STATION
    
    matches = context.user_data.get("station_matches", [])
    selected = next((m for m in matches if m["name"] == selection), None)
    
    if not selected:
        await update.message.reply_text(
            "Please select a station from the list or search again.",
            reply_markup=ReplyKeyboardRemove()
        )
        return RETURN_STATION
    
    context.user_data["preferences"]["return_station_name"] = selected["name"]
    context.user_data["preferences"]["return_station_code"] = selected["nlc"]
    
    await update.message.reply_text(
        f"✅ Return station: *{selected['name']}*\n\n"
        "Which day of the week do you usually *return*?",
        parse_mode="Markdown",
        reply_markup=get_day_keyboard()
    )
    
    return RETURN_DAY


async def return_day(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle return day selection."""
    day = update.message.text.strip()
    
    if day not in DAYS_OF_WEEK:
        await update.message.reply_text(
            "Please select a day from the list:",
            reply_markup=get_day_keyboard()
        )
        return RETURN_DAY
    
    context.user_data["preferences"]["return_day"] = day
    
    await update.message.reply_text(
        f"✅ Return day: *{day}*\n\n"
        "What time do you usually return?",
        parse_mode="Markdown",
        reply_markup=get_time_keyboard()
    )
    
    return RETURN_TIME


async def return_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle return time selection."""
    time_str = update.message.text.strip()
    
    if time_str not in TIME_SLOTS:
        await update.message.reply_text(
            "Please select a time from the list:",
            reply_markup=get_time_keyboard()
        )
        return RETURN_TIME
    
    context.user_data["preferences"]["return_time"] = time_str
    
    await update.message.reply_text(
        f"✅ Return time: *{time_str}*\n\n"
        "Now let's set up your *fare alert thresholds*.\n\n"
        "What's the maximum price (in £) you'd like to pay for your *outbound* journey?\n"
        "Fares below this will be highlighted with 🔥\n\n"
        "Enter a price (e.g., `40` for £40):",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )
    
    return OUTBOUND_THRESHOLD


async def outbound_threshold(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle outbound fare threshold input."""
    text = update.message.text.strip().replace("£", "")
    
    try:
        threshold = float(text)
        threshold_pence = int(threshold * 100)
    except ValueError:
        await update.message.reply_text(
            "❌ Invalid price. Please enter a number (e.g., `40` for £40):",
            parse_mode="Markdown"
        )
        return OUTBOUND_THRESHOLD
    
    context.user_data["preferences"]["outbound_fare_threshold"] = threshold_pence
    
    await update.message.reply_text(
        f"✅ Outbound threshold: *£{threshold:.2f}*\n\n"
        "What's the maximum price (in £) for your *return* journey?\n"
        "Enter a price (e.g., `65` for £65):",
        parse_mode="Markdown"
    )
    
    return RETURN_THRESHOLD


async def return_threshold(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle return fare threshold input."""
    text = update.message.text.strip().replace("£", "")
    
    try:
        threshold = float(text)
        threshold_pence = int(threshold * 100)
    except ValueError:
        await update.message.reply_text(
            "❌ Invalid price. Please enter a number (e.g., `65` for £65):",
            parse_mode="Markdown"
        )
        return RETURN_THRESHOLD
    
    context.user_data["preferences"]["return_fare_threshold"] = threshold_pence
    context.user_data["selected_days"] = []
    
    await update.message.reply_text(
        f"✅ Return threshold: *£{threshold:.2f}*\n\n"
        "Finally, let's set up when you'd like to receive fare updates.\n\n"
        "Select the *first day* you'd like to receive messages:",
        parse_mode="Markdown",
        reply_markup=get_day_keyboard()
    )
    
    return MESSAGE_DAYS


async def message_days(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle message days selection."""
    day = update.message.text.strip()
    
    if day not in DAYS_OF_WEEK:
        await update.message.reply_text(
            "Please select a day from the list:",
            reply_markup=get_day_keyboard()
        )
        return MESSAGE_DAYS
    
    selected_days = context.user_data.get("selected_days", [])
    
    if day in selected_days:
        await update.message.reply_text(
            f"You already selected {day}. Please choose a different day:",
            reply_markup=get_day_keyboard(exclude=selected_days)
        )
        return MESSAGE_DAYS
    
    selected_days.append(day)
    context.user_data["selected_days"] = selected_days
    
    if len(selected_days) < 2:
        await update.message.reply_text(
            f"✅ First message day: *{day}*\n\n"
            "Select the *second day* you'd like to receive messages:",
            parse_mode="Markdown",
            reply_markup=get_day_keyboard(exclude=selected_days)
        )
        return MESSAGE_DAYS
    
    context.user_data["preferences"]["message_days"] = selected_days
    
    await update.message.reply_text(
        f"✅ Message days: *{selected_days[0]}* and *{selected_days[1]}*\n\n"
        "What time would you like to receive these updates?",
        parse_mode="Markdown",
        reply_markup=get_time_keyboard()
    )
    
    return MESSAGE_TIME


async def message_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle message time selection."""
    time_str = update.message.text.strip()
    
    if time_str not in TIME_SLOTS:
        await update.message.reply_text(
            "Please select a time from the list:",
            reply_markup=get_time_keyboard()
        )
        return MESSAGE_TIME
    
    context.user_data["preferences"]["message_time"] = time_str
    
    await update.message.reply_text(
        f"✅ Message time: *{time_str}*\n\n"
        "Finally, how many months ahead would you like to search for fares?",
        parse_mode="Markdown",
        reply_markup=get_period_keyboard()
    )
    
    return PERIOD_IN_MONTHS


async def period_in_months(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle period in months selection and complete setup."""
    text = update.message.text.strip()
    
    # Parse "X month(s)" format
    try:
        months = int(text.replace(" months", "").replace(" month", ""))
        if months not in PERIOD_OPTIONS:
            raise ValueError()
    except ValueError:
        await update.message.reply_text(
            "Please select a period from the list:",
            reply_markup=get_period_keyboard()
        )
        return PERIOD_IN_MONTHS
    
    context.user_data["preferences"]["period_in_months"] = months
    
    # Save all preferences
    prefs = context.user_data["preferences"]
    chat_id = update.effective_chat.id
    save_user_preferences(chat_id, prefs)
    
    # Clean up user_data
    context.user_data.pop("locations", None)
    context.user_data.pop("station_matches", None)
    context.user_data.pop("selected_days", None)
    
    # Build summary
    summary = (
        "🎉 *Setup Complete!*\n\n"
        "*Your Journey:*\n"
        f"📍 From: {prefs['start_station_name']}\n"
        f"📍 To: {prefs['return_station_name']}\n\n"
        "*Outbound:*\n"
        f"📅 {prefs['outbound_day']} at {prefs['outbound_time']}\n"
        f"💰 Alert if under £{prefs['outbound_fare_threshold'] / 100:.2f}\n\n"
        "*Return:*\n"
        f"📅 {prefs['return_day']} at {prefs['return_time']}\n"
        f"💰 Alert if under £{prefs['return_fare_threshold'] / 100:.2f}\n\n"
        "*Updates:*\n"
        f"📬 {prefs['message_days'][0]} & {prefs['message_days'][1]} at {prefs['message_time']}\n"
        f"🔭 Searching {prefs['period_in_months']} month{'s' if prefs['period_in_months'] > 1 else ''} ahead\n\n"
        "*Commands:*\n"
        "/check - Get fares now\n"
        "/settings - View your settings\n"
        "/change - Modify a setting\n"
        "/stop - Unsubscribe"
    )
    
    await update.message.reply_text(summary, parse_mode="Markdown", reply_markup=ReplyKeyboardRemove())
    
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the setup conversation."""
    context.user_data.clear()
    await update.message.reply_text(
        "Setup cancelled. Use /start to begin again.",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /stop command - unsubscribe from updates."""
    chat_id = update.effective_chat.id
    was_subscribed = remove_user(chat_id)
    
    if was_subscribed:
        await update.message.reply_text(
            "👋 You've been unsubscribed from train fare updates.\n\n"
            "Use /start to set up again.",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            "You weren't subscribed. Use /start to set up.",
            parse_mode="Markdown"
        )


async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /settings command - show current preferences."""
    chat_id = update.effective_chat.id
    prefs = get_user_preferences(chat_id)
    
    if not prefs:
        await update.message.reply_text(
            "You haven't set up your preferences yet.\n\n"
            "Use /start to begin setup."
        )
        return
    
    summary = (
        "⚙️ *Your Settings*\n\n"
        "*Your Journey:*\n"
        f"📍 From: {prefs.get('start_station_name', 'N/A')}\n"
        f"📍 To: {prefs.get('return_station_name', 'N/A')}\n\n"
        "*Outbound:*\n"
        f"📅 {prefs.get('outbound_day', 'N/A')} at {prefs.get('outbound_time', 'N/A')}\n"
        f"💰 Alert if under £{prefs.get('outbound_fare_threshold', 0) / 100:.2f}\n\n"
        "*Return:*\n"
        f"📅 {prefs.get('return_day', 'N/A')} at {prefs.get('return_time', 'N/A')}\n"
        f"💰 Alert if under £{prefs.get('return_fare_threshold', 0) / 100:.2f}\n\n"
        "*Updates:*\n"
        f"📬 {' & '.join(prefs.get('message_days', ['N/A']))} at {prefs.get('message_time', 'N/A')}\n"
        f"🔭 Searching {prefs.get('period_in_months', 'N/A')} month(s) ahead\n\n"
        "Use /change to modify a setting, or /start to reconfigure all."
    )
    
    await update.message.reply_text(summary, parse_mode="Markdown")


# ============== Change Settings Handlers ==============

CHANGE_SETTINGS_MENU = [
    ["📍 Departure Station", "📍 Return Station"],
    ["📅 Outbound Day", "⏰ Outbound Time"],
    ["📅 Return Day", "⏰ Return Time"],
    ["💰 Outbound Threshold", "💰 Return Threshold"],
    ["📬 Message Days", "⏰ Message Time"],
    ["🔭 Search Period"],
    ["❌ Cancel"]
]


def get_change_menu_keyboard() -> ReplyKeyboardMarkup:
    """Create a keyboard with change settings menu."""
    return ReplyKeyboardMarkup(CHANGE_SETTINGS_MENU, one_time_keyboard=True, resize_keyboard=True)


async def change_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /change command - show menu of settings to change."""
    chat_id = update.effective_chat.id
    prefs = get_user_preferences(chat_id)
    
    if not prefs:
        await update.message.reply_text(
            "You haven't set up your preferences yet.\n\n"
            "Use /start to begin setup."
        )
        return ConversationHandler.END
    
    # Load locations for station searches
    context.user_data["locations"] = load_locations()
    
    await update.message.reply_text(
        "⚙️ *Change Settings*\n\n"
        "Select the setting you'd like to change:",
        parse_mode="Markdown",
        reply_markup=get_change_menu_keyboard()
    )
    
    return CHANGE_MENU


async def change_menu_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle menu selection for changing settings."""
    selection = update.message.text.strip()
    chat_id = update.effective_chat.id
    prefs = get_user_preferences(chat_id)
    
    if selection == "❌ Cancel":
        context.user_data.pop("locations", None)
        await update.message.reply_text(
            "Settings change cancelled.",
            reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END
    
    if selection == "📍 Departure Station":
        await update.message.reply_text(
            f"Current departure station: *{prefs.get('start_station_name', 'N/A')}*\n\n"
            "Type the name of your new departure station:",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove()
        )
        return CHANGE_START_STATION
    
    elif selection == "📍 Return Station":
        await update.message.reply_text(
            f"Current return station: *{prefs.get('return_station_name', 'N/A')}*\n\n"
            "Type the name of your new return station:",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove()
        )
        return CHANGE_RETURN_STATION
    
    elif selection == "📅 Outbound Day":
        await update.message.reply_text(
            f"Current outbound day: *{prefs.get('outbound_day', 'N/A')}*\n\n"
            "Select your new outbound day:",
            parse_mode="Markdown",
            reply_markup=get_day_keyboard()
        )
        return CHANGE_OUTBOUND_DAY
    
    elif selection == "⏰ Outbound Time":
        await update.message.reply_text(
            f"Current outbound time: *{prefs.get('outbound_time', 'N/A')}*\n\n"
            "Select your new outbound time:",
            parse_mode="Markdown",
            reply_markup=get_time_keyboard()
        )
        return CHANGE_OUTBOUND_TIME
    
    elif selection == "📅 Return Day":
        await update.message.reply_text(
            f"Current return day: *{prefs.get('return_day', 'N/A')}*\n\n"
            "Select your new return day:",
            parse_mode="Markdown",
            reply_markup=get_day_keyboard()
        )
        return CHANGE_RETURN_DAY
    
    elif selection == "⏰ Return Time":
        await update.message.reply_text(
            f"Current return time: *{prefs.get('return_time', 'N/A')}*\n\n"
            "Select your new return time:",
            parse_mode="Markdown",
            reply_markup=get_time_keyboard()
        )
        return CHANGE_RETURN_TIME
    
    elif selection == "💰 Outbound Threshold":
        current = prefs.get('outbound_fare_threshold', 0) / 100
        await update.message.reply_text(
            f"Current outbound threshold: *£{current:.2f}*\n\n"
            "Enter your new maximum outbound fare (e.g., `40` for £40):",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove()
        )
        return CHANGE_OUTBOUND_THRESHOLD
    
    elif selection == "💰 Return Threshold":
        current = prefs.get('return_fare_threshold', 0) / 100
        await update.message.reply_text(
            f"Current return threshold: *£{current:.2f}*\n\n"
            "Enter your new maximum return fare (e.g., `65` for £65):",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove()
        )
        return CHANGE_RETURN_THRESHOLD
    
    elif selection == "📬 Message Days":
        current_days = prefs.get('message_days', [])
        await update.message.reply_text(
            f"Current message days: *{' & '.join(current_days) if current_days else 'N/A'}*\n\n"
            "Select the *first* day you'd like to receive messages:",
            parse_mode="Markdown",
            reply_markup=get_day_keyboard()
        )
        context.user_data["new_message_days"] = []
        return CHANGE_MESSAGE_DAYS
    
    elif selection == "⏰ Message Time":
        await update.message.reply_text(
            f"Current message time: *{prefs.get('message_time', 'N/A')}*\n\n"
            "Select your new message time:",
            parse_mode="Markdown",
            reply_markup=get_time_keyboard()
        )
        return CHANGE_MESSAGE_TIME
    
    elif selection == "🔭 Search Period":
        current = prefs.get('period_in_months', 'N/A')
        await update.message.reply_text(
            f"Current search period: *{current} month{'s' if current != 1 else ''}*\n\n"
            "Select how many months ahead to search:",
            parse_mode="Markdown",
            reply_markup=get_period_keyboard()
        )
        return CHANGE_PERIOD
    
    else:
        await update.message.reply_text(
            "Please select an option from the menu:",
            reply_markup=get_change_menu_keyboard()
        )
        return CHANGE_MENU


async def change_start_station_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Search for new start station."""
    query = update.message.text.strip()
    locations = context.user_data.get("locations", [])
    
    matches = search_stations(query, locations)
    
    if not matches:
        await update.message.reply_text(
            f"❌ No stations found matching '{query}'.\n\n"
            "Please try again with a different search term:"
        )
        return CHANGE_START_STATION
    
    context.user_data["station_matches"] = matches
    
    keyboard = [[m["name"]] for m in matches]
    keyboard.append(["🔍 Search again"])
    keyboard.append(["❌ Cancel"])
    
    await update.message.reply_text(
        f"Found {len(matches)} station(s) matching '{query}'.\n\n"
        "Select your new departure station:",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    
    return CHANGE_SELECT_START_STATION


async def change_select_start_station(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle new start station selection."""
    selection = update.message.text.strip()
    chat_id = update.effective_chat.id
    
    if selection == "❌ Cancel":
        context.user_data.pop("locations", None)
        context.user_data.pop("station_matches", None)
        await update.message.reply_text(
            "Settings change cancelled.",
            reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END
    
    if selection == "🔍 Search again":
        await update.message.reply_text(
            "Type the name of your new departure station:",
            reply_markup=ReplyKeyboardRemove()
        )
        return CHANGE_START_STATION
    
    matches = context.user_data.get("station_matches", [])
    selected = next((m for m in matches if m["name"] == selection), None)
    
    if not selected:
        await update.message.reply_text(
            "Please select a station from the list or search again.",
            reply_markup=ReplyKeyboardRemove()
        )
        return CHANGE_START_STATION
    
    # Update preferences
    prefs = get_user_preferences(chat_id)
    prefs["start_station_name"] = selected["name"]
    prefs["start_station_code"] = selected["nlc"]
    save_user_preferences(chat_id, prefs)
    
    context.user_data.pop("locations", None)
    context.user_data.pop("station_matches", None)
    
    await update.message.reply_text(
        f"✅ Departure station updated to *{selected['name']}*",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )
    
    return ConversationHandler.END


async def change_return_station_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Search for new return station."""
    query = update.message.text.strip()
    locations = context.user_data.get("locations", [])
    
    matches = search_stations(query, locations)
    
    if not matches:
        await update.message.reply_text(
            f"❌ No stations found matching '{query}'.\n\n"
            "Please try again with a different search term:"
        )
        return CHANGE_RETURN_STATION
    
    context.user_data["station_matches"] = matches
    
    keyboard = [[m["name"]] for m in matches]
    keyboard.append(["🔍 Search again"])
    keyboard.append(["❌ Cancel"])
    
    await update.message.reply_text(
        f"Found {len(matches)} station(s) matching '{query}'.\n\n"
        "Select your new return station:",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    
    return CHANGE_SELECT_RETURN_STATION


async def change_select_return_station(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle new return station selection."""
    selection = update.message.text.strip()
    chat_id = update.effective_chat.id
    
    if selection == "❌ Cancel":
        context.user_data.pop("locations", None)
        context.user_data.pop("station_matches", None)
        await update.message.reply_text(
            "Settings change cancelled.",
            reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END
    
    if selection == "🔍 Search again":
        await update.message.reply_text(
            "Type the name of your new return station:",
            reply_markup=ReplyKeyboardRemove()
        )
        return CHANGE_RETURN_STATION
    
    matches = context.user_data.get("station_matches", [])
    selected = next((m for m in matches if m["name"] == selection), None)
    
    if not selected:
        await update.message.reply_text(
            "Please select a station from the list or search again.",
            reply_markup=ReplyKeyboardRemove()
        )
        return CHANGE_RETURN_STATION
    
    # Update preferences
    prefs = get_user_preferences(chat_id)
    prefs["return_station_name"] = selected["name"]
    prefs["return_station_code"] = selected["nlc"]
    save_user_preferences(chat_id, prefs)
    
    context.user_data.pop("locations", None)
    context.user_data.pop("station_matches", None)
    
    await update.message.reply_text(
        f"✅ Return station updated to *{selected['name']}*",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )
    
    return ConversationHandler.END


async def change_outbound_day(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle new outbound day selection."""
    day = update.message.text.strip()
    chat_id = update.effective_chat.id
    
    if day not in DAYS_OF_WEEK:
        await update.message.reply_text(
            "Please select a day from the list:",
            reply_markup=get_day_keyboard()
        )
        return CHANGE_OUTBOUND_DAY
    
    prefs = get_user_preferences(chat_id)
    prefs["outbound_day"] = day
    save_user_preferences(chat_id, prefs)
    
    await update.message.reply_text(
        f"✅ Outbound day updated to *{day}*",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )
    
    return ConversationHandler.END


async def change_outbound_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle new outbound time selection."""
    time_str = update.message.text.strip()
    chat_id = update.effective_chat.id
    
    if time_str not in TIME_SLOTS:
        await update.message.reply_text(
            "Please select a time from the list:",
            reply_markup=get_time_keyboard()
        )
        return CHANGE_OUTBOUND_TIME
    
    prefs = get_user_preferences(chat_id)
    prefs["outbound_time"] = time_str
    save_user_preferences(chat_id, prefs)
    
    await update.message.reply_text(
        f"✅ Outbound time updated to *{time_str}*",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )
    
    return ConversationHandler.END


async def change_return_day(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle new return day selection."""
    day = update.message.text.strip()
    chat_id = update.effective_chat.id
    
    if day not in DAYS_OF_WEEK:
        await update.message.reply_text(
            "Please select a day from the list:",
            reply_markup=get_day_keyboard()
        )
        return CHANGE_RETURN_DAY
    
    prefs = get_user_preferences(chat_id)
    prefs["return_day"] = day
    save_user_preferences(chat_id, prefs)
    
    await update.message.reply_text(
        f"✅ Return day updated to *{day}*",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )
    
    return ConversationHandler.END


async def change_return_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle new return time selection."""
    time_str = update.message.text.strip()
    chat_id = update.effective_chat.id
    
    if time_str not in TIME_SLOTS:
        await update.message.reply_text(
            "Please select a time from the list:",
            reply_markup=get_time_keyboard()
        )
        return CHANGE_RETURN_TIME
    
    prefs = get_user_preferences(chat_id)
    prefs["return_time"] = time_str
    save_user_preferences(chat_id, prefs)
    
    await update.message.reply_text(
        f"✅ Return time updated to *{time_str}*",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )
    
    return ConversationHandler.END


async def change_outbound_threshold(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle new outbound threshold input."""
    text = update.message.text.strip().replace("£", "")
    chat_id = update.effective_chat.id
    
    try:
        threshold = float(text)
        threshold_pence = int(threshold * 100)
    except ValueError:
        await update.message.reply_text(
            "❌ Invalid price. Please enter a number (e.g., `40` for £40):",
            parse_mode="Markdown"
        )
        return CHANGE_OUTBOUND_THRESHOLD
    
    prefs = get_user_preferences(chat_id)
    prefs["outbound_fare_threshold"] = threshold_pence
    save_user_preferences(chat_id, prefs)
    
    await update.message.reply_text(
        f"✅ Outbound threshold updated to *£{threshold:.2f}*",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )
    
    return ConversationHandler.END


async def change_return_threshold(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle new return threshold input."""
    text = update.message.text.strip().replace("£", "")
    chat_id = update.effective_chat.id
    
    try:
        threshold = float(text)
        threshold_pence = int(threshold * 100)
    except ValueError:
        await update.message.reply_text(
            "❌ Invalid price. Please enter a number (e.g., `65` for £65):",
            parse_mode="Markdown"
        )
        return CHANGE_RETURN_THRESHOLD
    
    prefs = get_user_preferences(chat_id)
    prefs["return_fare_threshold"] = threshold_pence
    save_user_preferences(chat_id, prefs)
    
    await update.message.reply_text(
        f"✅ Return threshold updated to *£{threshold:.2f}*",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )
    
    return ConversationHandler.END


async def change_message_days(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle first message day selection."""
    day = update.message.text.strip()
    
    if day not in DAYS_OF_WEEK:
        await update.message.reply_text(
            "Please select a day from the list:",
            reply_markup=get_day_keyboard()
        )
        return CHANGE_MESSAGE_DAYS
    
    context.user_data["new_message_days"] = [day]
    
    await update.message.reply_text(
        f"✅ First message day: *{day}*\n\n"
        "Select the *second* day you'd like to receive messages:",
        parse_mode="Markdown",
        reply_markup=get_day_keyboard(exclude=[day])
    )
    
    return CHANGE_MESSAGE_DAYS_SECOND


async def change_message_days_second(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle second message day selection."""
    day = update.message.text.strip()
    chat_id = update.effective_chat.id
    first_day = context.user_data.get("new_message_days", [])[0] if context.user_data.get("new_message_days") else None
    
    if day not in DAYS_OF_WEEK or day == first_day:
        await update.message.reply_text(
            "Please select a different day from the list:",
            reply_markup=get_day_keyboard(exclude=[first_day] if first_day else [])
        )
        return CHANGE_MESSAGE_DAYS_SECOND
    
    new_days = [first_day, day]
    
    prefs = get_user_preferences(chat_id)
    prefs["message_days"] = new_days
    save_user_preferences(chat_id, prefs)
    
    context.user_data.pop("new_message_days", None)
    
    await update.message.reply_text(
        f"✅ Message days updated to *{new_days[0]}* & *{new_days[1]}*",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )
    
    return ConversationHandler.END


async def change_message_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle new message time selection."""
    time_str = update.message.text.strip()
    chat_id = update.effective_chat.id
    
    if time_str not in TIME_SLOTS:
        await update.message.reply_text(
            "Please select a time from the list:",
            reply_markup=get_time_keyboard()
        )
        return CHANGE_MESSAGE_TIME
    
    prefs = get_user_preferences(chat_id)
    prefs["message_time"] = time_str
    save_user_preferences(chat_id, prefs)
    
    await update.message.reply_text(
        f"✅ Message time updated to *{time_str}*",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )
    
    return ConversationHandler.END


async def change_period(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle new period selection."""
    text = update.message.text.strip()
    chat_id = update.effective_chat.id
    
    try:
        months = int(text.replace(" months", "").replace(" month", ""))
        if months not in PERIOD_OPTIONS:
            raise ValueError()
    except ValueError:
        await update.message.reply_text(
            "Please select a period from the list:",
            reply_markup=get_period_keyboard()
        )
        return CHANGE_PERIOD
    
    prefs = get_user_preferences(chat_id)
    prefs["period_in_months"] = months
    save_user_preferences(chat_id, prefs)
    
    await update.message.reply_text(
        f"✅ Search period updated to *{months} month{'s' if months > 1 else ''}*",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )
    
    return ConversationHandler.END


async def change_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the change settings conversation."""
    context.user_data.pop("locations", None)
    context.user_data.pop("station_matches", None)
    context.user_data.pop("new_message_days", None)
    
    await update.message.reply_text(
        "Settings change cancelled.",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END


async def check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /check command - manually trigger a fare check."""
    chat_id = update.effective_chat.id
    prefs = get_user_preferences(chat_id)
    
    if not prefs:
        await update.message.reply_text(
            "You haven't set up your preferences yet.\n\n"
            "Use /start to begin setup."
        )
        return
    
    # Check cooldown
    last_search = prefs.get("last_search")
    if last_search:
        last_search_time = datetime.fromisoformat(last_search)
        cooldown_delta = timedelta(hours=CHECK_COOLDOWN_HOURS)
        time_since_last = datetime.now() - last_search_time
        
        if time_since_last < cooldown_delta:
            remaining = cooldown_delta - time_since_last
            hours, remainder = divmod(int(remaining.total_seconds()), 3600)
            minutes = remainder // 60
            
            await update.message.reply_text(
                f"⏳ Please wait before checking again.\n\n"
                f"You can check again in *{hours}h {minutes}m*.\n\n"
                f"(Cooldown: {CHECK_COOLDOWN_HOURS} hours between manual checks)",
                parse_mode="Markdown"
            )
            return
    
    await update.message.reply_text("🔍 Fetching train fares...")
    
    try:
        message = fetch_train_fares(
            from_station_code=prefs.get("start_station_code"),
            to_station_code=prefs.get("return_station_code"),
            outbound_fare_threshold=prefs.get("outbound_fare_threshold", 4000),
            return_fare_threshold=prefs.get("return_fare_threshold", 6500),
            outbound_day_of_the_week=prefs.get("outbound_day", "Monday"),
            return_day_of_the_week=prefs.get("return_day", "Thursday"),
            outbound_time=prefs.get("outbound_time", "18:00"),
            return_time=prefs.get("return_time", "18:00"),
            months_ahead=prefs.get("period_in_months", 3),
        )
        
        # Update last_search timestamp
        prefs["last_search"] = datetime.now().isoformat()
        save_user_preferences(chat_id, prefs)
        
        await update.message.reply_text(message, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in /check command: {e}")
        await update.message.reply_text(f"❌ Error fetching fares: {e}")


async def send_fares_to_user(bot: Bot, chat_id: int, prefs: dict) -> None:
    """Send train fares to a specific user with their preferences."""
    try:
        message = fetch_train_fares(
            from_station_code=prefs.get("start_station_code"),
            to_station_code=prefs.get("return_station_code"),
            outbound_fare_threshold=prefs.get("outbound_fare_threshold", 4000),
            return_fare_threshold=prefs.get("return_fare_threshold", 6500),
            outbound_day_of_the_week=prefs.get("outbound_day", "Monday"),
            return_day_of_the_week=prefs.get("return_day", "Thursday"),
            outbound_time=prefs.get("outbound_time", "18:00"),
            return_time=prefs.get("return_time", "18:00"),
            months_ahead=prefs.get("period_in_months", 3),
        )
        
        await bot.send_message(
            chat_id=chat_id,
            text=message,
            parse_mode="Markdown"
        )
        logger.info(f"Sent fares to chat {chat_id}")
    except Exception as e:
        logger.error(f"Error sending fares to chat {chat_id}: {e}")


async def send_scheduled_fares() -> None:
    """Check for users scheduled at the current time and send fares."""
    if not BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable is required")
    
    current_time = datetime.now()
    matching_users = get_users_for_scheduled_time(current_time, tolerance_minutes=5)
    
    if not matching_users:
        logger.info(f"No users scheduled for {current_time.strftime('%A %H:%M')}")
        return
    
    logger.info(f"Found {len(matching_users)} user(s) scheduled for {current_time.strftime('%A %H:%M')}")
    
    bot = Bot(token=BOT_TOKEN)
    
    async with bot:
        # Run all user fetches concurrently
        tasks = [
            send_fares_to_user(bot, chat_id, prefs)
            for chat_id, prefs in matching_users
        ]
        await asyncio.gather(*tasks, return_exceptions=True)
    
    logger.info("Scheduled fares sent successfully")


def run_bot() -> None:
    """Run the bot in polling mode for interactive commands."""
    if not BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable is required")
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Conversation handler for setup
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            START_STATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, start_station_search)],
            SELECT_START_STATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_start_station)],
            OUTBOUND_DAY: [MessageHandler(filters.TEXT & ~filters.COMMAND, outbound_day)],
            OUTBOUND_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, outbound_time)],
            RETURN_STATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, return_station_search)],
            SELECT_RETURN_STATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_return_station)],
            RETURN_DAY: [MessageHandler(filters.TEXT & ~filters.COMMAND, return_day)],
            RETURN_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, return_time)],
            OUTBOUND_THRESHOLD: [MessageHandler(filters.TEXT & ~filters.COMMAND, outbound_threshold)],
            RETURN_THRESHOLD: [MessageHandler(filters.TEXT & ~filters.COMMAND, return_threshold)],
            MESSAGE_DAYS: [MessageHandler(filters.TEXT & ~filters.COMMAND, message_days)],
            MESSAGE_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, message_time)],
            PERIOD_IN_MONTHS: [MessageHandler(filters.TEXT & ~filters.COMMAND, period_in_months)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    
    # Change settings conversation handler
    change_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("change", change_settings)],
        states={
            CHANGE_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, change_menu_selection)],
            CHANGE_START_STATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, change_start_station_search)],
            CHANGE_SELECT_START_STATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, change_select_start_station)],
            CHANGE_RETURN_STATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, change_return_station_search)],
            CHANGE_SELECT_RETURN_STATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, change_select_return_station)],
            CHANGE_OUTBOUND_DAY: [MessageHandler(filters.TEXT & ~filters.COMMAND, change_outbound_day)],
            CHANGE_OUTBOUND_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, change_outbound_time)],
            CHANGE_RETURN_DAY: [MessageHandler(filters.TEXT & ~filters.COMMAND, change_return_day)],
            CHANGE_RETURN_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, change_return_time)],
            CHANGE_OUTBOUND_THRESHOLD: [MessageHandler(filters.TEXT & ~filters.COMMAND, change_outbound_threshold)],
            CHANGE_RETURN_THRESHOLD: [MessageHandler(filters.TEXT & ~filters.COMMAND, change_return_threshold)],
            CHANGE_MESSAGE_DAYS: [MessageHandler(filters.TEXT & ~filters.COMMAND, change_message_days)],
            CHANGE_MESSAGE_DAYS_SECOND: [MessageHandler(filters.TEXT & ~filters.COMMAND, change_message_days_second)],
            CHANGE_MESSAGE_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, change_message_time)],
            CHANGE_PERIOD: [MessageHandler(filters.TEXT & ~filters.COMMAND, change_period)],
        },
        fallbacks=[CommandHandler("cancel", change_cancel)],
    )
    
    application.add_handler(conv_handler)
    application.add_handler(change_conv_handler)
    application.add_handler(CommandHandler("stop", stop))
    application.add_handler(CommandHandler("settings", settings))
    application.add_handler(CommandHandler("check", check))
    
    logger.info("Starting bot in polling mode...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


def main() -> None:
    """Main entry point."""
    if len(sys.argv) > 1 and sys.argv[1] == "scheduled":
        logger.info("Running in scheduled mode...")
        asyncio.run(send_scheduled_fares())
    else:
        run_bot()


if __name__ == "__main__":
    main()
