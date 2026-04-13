import asyncio
import os
import time
from collections import defaultdict
from dotenv import load_dotenv
from db import save_user, get_user_count
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    ApplicationHandlerStop,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

load_dotenv()

BOT_TOKEN = os.environ.get("BOT_TOKEN")

# ConversationHandler states
SELECT_DAY, SELECT_STATION, SELECT_DIRECTION, SELECT_USE_SAVED, SELECT_TT_FROM, SELECT_TT_TO = range(6)


# ── /next Guided Menu ─────────────────────────────────────────────────────────

CANCEL_BTN = InlineKeyboardButton("Cancel", callback_data="cancel")

WELCOME_TEXT = (
    "👋 Welcome to TimelyCal!\n\n"
    "I'm your personal Caltrain schedule assistant. Just ask me anything about train timings in plain English!\n\n"
    "Try asking:\n"
    "• When is the next train from Lawrence to SF?\n"
    "• What's the last train from Palo Alto on weekends?\n"
    "• How long does it take from Sunnyvale to San Francisco?\n\n"
    "Or use the commands:\n"
    "/next         - Next 3 trains from a station\n"
    "/schedule     - Full day timetable for a station\n"
    "/traveltime   - Travel time between two stations\n"
    "/mystation    - Save your home station for quick access\n"
    "/help         - Show help anytime\n\n"
    "Let's get you on the right train! 🚂"
)

HELP_TEXT = (
    "I'm TimelyCal — ask me anything about the Caltrain schedule!\n\n"
    "Examples:\n"
    "• What time is the next train from SF to San Jose?\n"
    "• When is the last train on weekends?\n"
    "• How long does it take from Millbrae to Palo Alto?\n\n"
    "Commands:\n"
    "/next         - Next 3 trains from a station\n"
    "/schedule     - Full day timetable for a station\n"
    "/traveltime   - Travel time between two stations\n"
    "/mystation    - View or change your saved station\n"
    "/help         - Show this message"
)


async def _cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(HELP_TEXT)
    return ConversationHandler.END


async def ask_day_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    import pytz
    from datetime import datetime
    from services.schedule import STATIONS


    pacific = pytz.timezone("America/Los_Angeles")
    today = datetime.now(pacific).weekday()
    context.user_data["day_type"] = "weekday" if today < 5 else "weekend"

    buttons = [InlineKeyboardButton(s, callback_data=f"sta:{s}") for s in STATIONS]
    keyboard = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    keyboard.append([CANCEL_BTN])
    await update.message.reply_text(
        "Select your station:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return SELECT_STATION


async def show_both_directions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show next 3 trains in both directions for the selected station."""
    import pytz
    from datetime import datetime
    from services.schedule import get_next_trains, _train_label

    query = update.callback_query
    await query.answer()

    context.user_data["station"] = query.data.split(":", 1)[1]

    station = context.user_data["station"]
    day_type = context.user_data["day_type"]

    pacific = pytz.timezone("America/Los_Angeles")
    now_dt = datetime.now(pacific)
    now_time = now_dt.time()
    date_str = now_dt.strftime("%A, %b %d %Y")
    time_str = now_dt.strftime("%I:%M %p").lstrip("0")
    day_label = "Weekday" if day_type == "weekday" else "Weekend"

    now_mins = now_time.hour * 60 + now_time.minute

    def format_trains(direction):
        trains = get_next_trains(station, day_type, direction)
        if not trains:
            return "No upcoming trains."
        lines = []
        for t in trains:
            train_mins = t["time"].hour * 60 + t["time"].minute
            diff = train_mins - now_mins
            if diff < 0:
                diff += 24 * 60
            lines.append(f"Train {t['train']}{_train_label(t['train'])} — {t['time_str']} (in {diff} mins)")
        return "\n".join(lines)

    _SF_TERMINAL = "San Francisco"
    _SJ_TERMINALS = {"San Jose Diridon", "Tamien"}
    show_sf = station != _SF_TERMINAL
    show_sj = station not in _SJ_TERMINALS

    parts = [f"📍 {station}\n🗓 {date_str} | {time_str} ({day_label})"]
    if show_sf:
        parts.append(f"➡️ Towards San Francisco\n{format_trains('sf')}")
    if show_sj:
        parts.append(f"➡️ Towards San Jose\n{format_trains('sj')}")
    parts.append("⚠️ Schedule-based only. Not real-time.")
    text = "\n\n".join(parts)

    await query.edit_message_text(text)
    return ConversationHandler.END


async def handle_change_station(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """User chose to pick a different station — auto-detect day type, go to station selection."""
    from services.schedule import STATIONS

    query = update.callback_query
    await query.answer()

    buttons = [InlineKeyboardButton(s, callback_data=f"sta:{s}") for s in STATIONS]
    keyboard = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    keyboard.append([CANCEL_BTN])
    await query.edit_message_text(
        "Select your station:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return SELECT_STATION


async def ask_station(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    from services.schedule import STATIONS

    query = update.callback_query
    await query.answer()
    context.user_data["day_type"] = query.data.split(":")[1]

    buttons = [InlineKeyboardButton(s, callback_data=f"sta:{s}") for s in STATIONS]
    keyboard = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    keyboard.append([CANCEL_BTN])

    await query.edit_message_text(
        "Step 2 of 3: Select your station:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return SELECT_STATION




async def cancel_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(HELP_TEXT)
    return ConversationHandler.END


# ── /timing Full Timetable Menu ────────────────────────────────────────────────

async def ask_timing_day(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    from services.user_prefs import get_preference


    pref = get_preference(update.effective_user.id)
    if pref:
        station = pref["preferred_station"]
        context.user_data["station"] = station
        keyboard = [
            [InlineKeyboardButton(f"Use {station}", callback_data="tuse_saved")],
            [InlineKeyboardButton("Choose different station", callback_data="tchange_station")],
            [CANCEL_BTN],
        ]
        await update.message.reply_text(
            f"Your saved station: {station}\nUse saved station or choose a new one?",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return SELECT_USE_SAVED
    else:
        keyboard = [
            [
                InlineKeyboardButton("Weekday", callback_data="tday:weekday"),
                InlineKeyboardButton("Weekend", callback_data="tday:weekend"),
            ],
            [CANCEL_BTN],
        ]
        await update.message.reply_text(
            "Step 1 of 3: Which schedule?",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return SELECT_DAY


async def handle_timing_use_saved(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """User chose to use saved station for /timing — auto-detect day type, go to direction."""
    import pytz
    from datetime import datetime

    query = update.callback_query
    await query.answer()

    pacific = pytz.timezone("America/Los_Angeles")
    today = datetime.now(pacific).weekday()
    context.user_data["day_type"] = "weekday" if today < 5 else "weekend"

    keyboard = [
        [
            InlineKeyboardButton("Towards San Francisco", callback_data="tdir:sf"),
            InlineKeyboardButton("Towards San Jose", callback_data="tdir:sj"),
        ],
        [CANCEL_BTN],
    ]
    await query.edit_message_text(
        "Which direction?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return SELECT_DIRECTION


async def handle_timing_change_station(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """User chose to pick a different station for /timing."""
    query = update.callback_query
    await query.answer()

    keyboard = [
        [
            InlineKeyboardButton("Weekday", callback_data="tday:weekday"),
            InlineKeyboardButton("Weekend", callback_data="tday:weekend"),
        ],
        [CANCEL_BTN],
    ]
    await query.edit_message_text(
        "Step 1 of 3: Which schedule?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return SELECT_DAY


async def ask_timing_station(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    from services.schedule import STATIONS

    query = update.callback_query
    await query.answer()
    context.user_data["day_type"] = query.data.split(":")[1]

    buttons = [InlineKeyboardButton(s, callback_data=f"tsta:{s}") for s in STATIONS]
    keyboard = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    keyboard.append([CANCEL_BTN])

    await query.edit_message_text(
        "Step 2 of 3: Select your station:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return SELECT_STATION


async def ask_timing_direction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["station"] = query.data.split(":", 1)[1]

    keyboard = [
        [
            InlineKeyboardButton("Towards San Francisco", callback_data="tdir:sf"),
            InlineKeyboardButton("Towards San Jose", callback_data="tdir:sj"),
        ],
        [CANCEL_BTN],
    ]
    await query.edit_message_text(
        "Step 3 of 3: Which direction?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return SELECT_DIRECTION


async def show_timing_results(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    from services.schedule import get_all_trains, _train_label
    from services.user_prefs import get_preference

    query = update.callback_query
    await query.answer()

    direction = query.data.split(":")[1]
    station = context.user_data["station"]
    day_type = context.user_data["day_type"]
    dir_label = "San Francisco" if direction == "sf" else "San Jose"

    trains = get_all_trains(station, day_type, direction)

    if not trains:
        await query.edit_message_text(
            f"No trains found for {station} ({day_type.capitalize()}, towards {dir_label})."
        )
        return ConversationHandler.END

    from datetime import time as dt_time

    header = f"All trains from {station} towards {dir_label} ({day_type.capitalize()}):\n"

    morning   = [t for t in trains if t["time"] < dt_time(12, 0)]
    afternoon = [t for t in trains if dt_time(12, 0) <= t["time"] < dt_time(18, 0)]
    evening   = [t for t in trains if t["time"] >= dt_time(18, 0)]

    def section(label, items):
        if not items:
            return ""
        rows = "\n".join(f"Train {t['train']}{_train_label(t['train'])} — {t['time_str']}" for t in items)
        return f"{label}\n{rows}"

    body = "\n\n".join(
        s for s in [
            section("🌅 Morning (before 12pm)", morning),
            section("☀️ Afternoon (12pm – 6pm)", afternoon),
            section("🌙 Evening (after 6pm)", evening),
        ] if s
    )

    await query.edit_message_text(header + "\n" + body)

    # Offer to save station if no preference is set
    pref = get_preference(update.effective_user.id)
    if not pref:
        save_keyboard = [[
            InlineKeyboardButton(
                f"Save {station} as my default",
                callback_data=f"save_station:{station}",
            )
        ]]
        await query.message.reply_text(
            "Want to save this station for next time?",
            reply_markup=InlineKeyboardMarkup(save_keyboard),
        )

    return ConversationHandler.END


# ── Preference Callbacks (outside ConversationHandlers) ────────────────────────

async def save_station_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the 'Save X as my default' button."""
    from services.user_prefs import save_preference

    query = update.callback_query
    await query.answer()
    station = query.data.split(":", 1)[1]
    save_preference(update.effective_user.id, station)
    await query.edit_message_text(f"Saved! {station} is now your default station.")


# ── Command Handlers ──────────────────────────────────────────────────────────

async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"Hello {user.first_name}! I'm TimelyCal, your Caltrain assistant.\n\n"
        "Just type any question about the schedule, or use the commands:\n"
        "• /next for the next 3 trains from a station\n"
        "• /schedule for the full day timetable\n"
        "• /mystation to view or change your saved station\n\n"
        "Use /help to see more options."
    )


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(WELCOME_TEXT)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT)


async def mystation_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import pytz
    from datetime import datetime
    from services.user_prefs import get_preference
    from services.schedule import get_next_trains, _train_label, STATIONS


    pref = get_preference(update.effective_user.id)
    if not pref:
        buttons = [InlineKeyboardButton(s, callback_data=f"mset:{s}") for s in STATIONS]
        keyboard = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
        await update.message.reply_text(
            "No station saved yet. Select your default station:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    station = pref["preferred_station"]
    pacific = pytz.timezone("America/Los_Angeles")
    now_dt = datetime.now(pacific)
    now_time = now_dt.time()
    date_str = now_dt.strftime("%A, %b %d %Y")
    time_str = now_dt.strftime("%I:%M %p").lstrip("0")
    day_type = "weekday" if now_dt.weekday() < 5 else "weekend"
    day_label = "Weekday" if day_type == "weekday" else "Weekend"
    now_mins = now_time.hour * 60 + now_time.minute

    def format_trains(direction):
        trains = get_next_trains(station, day_type, direction)
        if not trains:
            return "No upcoming trains."
        lines = []
        for t in trains:
            train_mins = t["time"].hour * 60 + t["time"].minute
            diff = train_mins - now_mins
            if diff < 0:
                diff += 24 * 60
            lines.append(f"Train {t['train']}{_train_label(t['train'])} — {t['time_str']} (in {diff} mins)")
        return "\n".join(lines)

    _SF_TERMINAL = "San Francisco"
    _SJ_TERMINALS = {"San Jose Diridon", "Tamien"}
    show_sf = station != _SF_TERMINAL
    show_sj = station not in _SJ_TERMINALS

    parts = [f"📍 {station}\n🗓 {date_str} | {time_str} ({day_label})"]
    if show_sf:
        parts.append(f"➡️ Towards San Francisco\n{format_trains('sf')}")
    if show_sj:
        parts.append(f"➡️ Towards San Jose\n{format_trains('sj')}")
    parts.append("⚠️ Schedule-based only. Not real-time.")
    text = "\n\n".join(parts)

    keyboard = [[
        InlineKeyboardButton("Change station", callback_data="mystation_change"),
        InlineKeyboardButton("Clear station", callback_data="mystation_clear"),
    ]]
    await update.message.reply_text(text)
    await update.message.reply_text(
        "Manage your saved station:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def mystation_change_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from services.schedule import STATIONS

    query = update.callback_query
    await query.answer()

    buttons = [InlineKeyboardButton(s, callback_data=f"mset:{s}") for s in STATIONS]
    keyboard = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    await query.edit_message_text(
        "Select your new default station:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def mystation_set_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from services.user_prefs import save_preference

    query = update.callback_query
    await query.answer()
    station = query.data.split(":", 1)[1]
    save_preference(update.effective_user.id, station)
    await query.edit_message_text(f"Saved! {station} is now your default station.")


async def mystation_clear_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from supabase import create_client
    import os

    query = update.callback_query
    await query.answer()
    client = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY"))
    client.table("user_preferences").delete().eq("telegram_user_id", update.effective_user.id).execute()
    await query.edit_message_text("Your saved station has been cleared.")


async def echo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        text = " ".join(context.args)
        await update.message.reply_text(f"🔁 {text}")
    else:
        await update.message.reply_text("Usage: /echo <your message>")


# ── Message Handlers ──────────────────────────────────────────────────────────

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for plain text messages — queries the RAG pipeline."""
    from services.rag import query

    text = update.message.text
    try:
        answer = await asyncio.wait_for(
            asyncio.to_thread(query, text),
            timeout=10.0,
        )
    except asyncio.TimeoutError:
        await update.message.reply_text(
            "⏱ Sorry, that took too long. Please try again or use /schedule for the menu."
        )
        return
    except Exception:
        await update.message.reply_text("❌ Something went wrong. Please try again.")
        return
    await update.message.reply_text(answer)


async def handle_unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Sorry, I don't know that command. Use /help for options."
    )


# ── /traveltime ───────────────────────────────────────────────────────────────

async def ask_tt_from(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    from services.schedule import STATIONS
    buttons = [InlineKeyboardButton(s, callback_data=f"tt_from:{s}") for s in STATIONS]
    keyboard = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
    await update.message.reply_text(
        "Select your departure station:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return SELECT_TT_FROM


async def ask_tt_to(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    from services.schedule import STATIONS
    query = update.callback_query
    await query.answer()
    context.user_data["tt_from"] = query.data.split(":", 1)[1]

    buttons = [InlineKeyboardButton(s, callback_data=f"tt_to:{s}") for s in STATIONS]
    keyboard = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
    await query.edit_message_text(
        f"From: {context.user_data['tt_from']}\nNow select your destination station:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return SELECT_TT_TO


async def show_travel_times(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    import pytz
    from datetime import datetime
    from services.schedule import get_travel_times, STATIONS

    query = update.callback_query
    await query.answer()

    from_station = context.user_data["tt_from"]
    to_station = query.data.split(":", 1)[1]

    if from_station == to_station:
        await query.edit_message_text(
            "⚠️ Please pick a different destination station — origin and destination cannot be the same."
        )
        return ConversationHandler.END

    pacific = pytz.timezone("America/Los_Angeles")
    now_dt = datetime.now(pacific)
    now_time = now_dt.time()
    day_type = "weekday" if now_dt.weekday() < 5 else "weekend"

    # Fetch both directions: A→B and B→A (swapping from/to flips direction automatically)
    trains_ab = get_travel_times(from_station, to_station)
    trains_ba = get_travel_times(to_station, from_station)

    if not trains_ab and not trains_ba:
        await query.edit_message_text(
            f"No schedule data found for {from_station} ↔ {to_station} ({day_type.capitalize()}).\n"
            "This route may not be directly served by Caltrain."
        )
        return ConversationHandler.END

    # Determine which direction is towards SF vs SJ based on STATIONS geographic order
    from_idx = STATIONS.index(from_station)
    to_idx = STATIONS.index(to_station)
    if to_idx < from_idx:
        # A→B is towards SF, B→A is towards SJ
        trains_sf, trains_sj = trains_ab, trains_ba
    else:
        # A→B is towards SJ, B→A is towards SF
        trains_sf, trains_sj = trains_ba, trains_ab

    def _next(trains, label):
        """Return the next train of the given type after now, or None."""
        return next(
            (t for t in trains if t["label"] == label and t["depart"] >= now_time),
            None
        )

    def _duration(trains, label):
        """Return duration_mins from the first available train of this type (either direction)."""
        t = next((t for t in trains if t["label"] == label), None)
        return t["duration_mins"] if t else None

    def fmt_section(emoji, type_name, label, not_available_msg):
        # Check if this type exists in either direction at all
        all_of_type = [t for t in trains_sf + trains_sj if t["label"] == label]
        if not all_of_type:
            return f"{emoji} {type_name}\nℹ️ {not_available_msg}"

        duration = _duration(trains_sf + trains_sj, label)
        header = f"{emoji} {type_name} — ~{duration} mins" if duration else f"{emoji} {type_name}"

        next_sf = _next(trains_sf, label)
        next_sj = _next(trains_sj, label)

        sf_line = (
            f"  Towards San Francisco\n  Next: {next_sf['depart_str']} → {next_sf['arrive_str']}"
            if next_sf else
            "  Towards San Francisco\n  ℹ️ No more trains today."
        )
        sj_line = (
            f"  Towards San Jose\n  Next: {next_sj['depart_str']} → {next_sj['arrive_str']}"
            if next_sj else
            "  Towards San Jose\n  ℹ️ No more trains today."
        )
        return f"{header}\n\n{sf_line}\n\n{sj_line}"

    sections = [
        fmt_section("🚂", "Normal train",  "",          "Normal trains do not serve both stations."),
        fmt_section("⚡", "Limited train", " [Limited]", "Limited trains do not stop at one or both of these stations."),
        fmt_section("🚄", "Express train", " [Express]", "Express trains do not stop at one or both of these stations."),
    ]

    body = "\n\n".join(sections)
    header = f"🗺 {from_station} ↔ {to_station} ({day_type.capitalize()})\n\n"
    await query.edit_message_text(header + body + "\n\n⚠️ Schedule-based only. Not real-time.")
    return ConversationHandler.END


# ── Timeout & Error Handlers ──────────────────────────────────────────────────

async def _conversation_timeout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fired when a ConversationHandler times out due to inactivity."""
    await update.effective_message.reply_text(
        "⏱ Session timed out. Please start again."
    )


async def _error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Global error handler — logs and notifies the user on any unhandled exception."""
    logger.error("Unhandled exception", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text(
            "❌ Something went wrong. Please try again."
        )


# ── Per-User Rate Limiting ────────────────────────────────────────────────────

_user_message_times: dict[int, list[float]] = defaultdict(list)
_RATE_WINDOW = 60     # seconds
_RATE_MAX_MSGS = 10   # max messages per window


async def _rate_limit_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Block users sending more than 10 messages per minute."""
    if not update.effective_chat or not update.effective_message:
        return
    chat_id = update.effective_chat.id
    now = time.time()
    window_start = now - _RATE_WINDOW
    times = [t for t in _user_message_times[chat_id] if t > window_start]
    times.append(now)
    _user_message_times[chat_id] = times
    if len(times) > _RATE_MAX_MSGS:
        await update.effective_message.reply_text(
            "⚠️ You're sending messages too fast. Please wait a moment."
        )
        raise ApplicationHandlerStop


# ── User Tracking ─────────────────────────────────────────────────────────────

async def _track_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Silently record every user who interacts with the bot."""
    if update.effective_user and update.effective_chat:
        save_user(
            chat_id=update.effective_chat.id,
            username=update.effective_user.username,
        )


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    count = get_user_count()
    await update.message.reply_text(f"👥 Total unique users: {count}")


# ── Application Builder ───────────────────────────────────────────────────────

def get_application() -> Application:
    """Build and return the Telegram Application with all handlers registered."""
    app = Application.builder().token(BOT_TOKEN).build()

    # Rate limit per user (group=-2 runs before everything else)
    app.add_handler(MessageHandler(filters.ALL, _rate_limit_user), group=-2)

    # Track every incoming message silently (group=-1 runs before all other handlers)
    app.add_handler(MessageHandler(filters.ALL, _track_user), group=-1)

    # Guided schedule menu (ConversationHandler — must be registered before plain handlers)
    cancel_handler = CallbackQueryHandler(_cancel_callback, pattern="^cancel$")

    timeout_handler = [
        MessageHandler(filters.ALL, _conversation_timeout),
        CallbackQueryHandler(_conversation_timeout),
    ]

    schedule_conv = ConversationHandler(
        entry_points=[CommandHandler("next", ask_day_type)],
        states={
            SELECT_STATION: [cancel_handler, CallbackQueryHandler(show_both_directions, pattern="^sta:")],
            ConversationHandler.TIMEOUT: timeout_handler,
        },
        fallbacks=[CommandHandler("cancel", cancel_schedule)],
        allow_reentry=True,
        conversation_timeout=30,
    )
    app.add_handler(schedule_conv)

    # Full timetable menu
    timing_conv = ConversationHandler(
        entry_points=[CommandHandler("schedule", ask_timing_day)],
        states={
            SELECT_USE_SAVED: [
                cancel_handler,
                CallbackQueryHandler(handle_timing_use_saved, pattern="^tuse_saved$"),
                CallbackQueryHandler(handle_timing_change_station, pattern="^tchange_station$"),
            ],
            SELECT_DAY: [cancel_handler, CallbackQueryHandler(ask_timing_station, pattern="^tday:")],
            SELECT_STATION: [cancel_handler, CallbackQueryHandler(ask_timing_direction, pattern="^tsta:")],
            SELECT_DIRECTION: [cancel_handler, CallbackQueryHandler(show_timing_results, pattern="^tdir:")],
            ConversationHandler.TIMEOUT: timeout_handler,
        },
        fallbacks=[CommandHandler("cancel", cancel_schedule)],
        allow_reentry=True,
        conversation_timeout=30,
    )
    app.add_handler(timing_conv)

    # Travel time menu
    traveltime_conv = ConversationHandler(
        entry_points=[CommandHandler("traveltime", ask_tt_from)],
        states={
            SELECT_TT_FROM: [cancel_handler, CallbackQueryHandler(ask_tt_to, pattern="^tt_from:")],
            SELECT_TT_TO: [cancel_handler, CallbackQueryHandler(show_travel_times, pattern="^tt_to:")],
            ConversationHandler.TIMEOUT: timeout_handler,
        },
        fallbacks=[CommandHandler("cancel", cancel_schedule)],
        allow_reentry=True,
        conversation_timeout=30,
    )
    app.add_handler(traveltime_conv)

    # Standalone preference callbacks (outside ConversationHandlers)
    app.add_handler(CallbackQueryHandler(save_station_callback, pattern="^save_station:"))
    app.add_handler(CallbackQueryHandler(mystation_change_callback, pattern="^mystation_change$"))
    app.add_handler(CallbackQueryHandler(mystation_set_callback, pattern="^mset:"))
    app.add_handler(CallbackQueryHandler(mystation_clear_callback, pattern="^mystation_clear$"))

    # Standard command handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("ask", ask_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("mystation", mystation_command))
    app.add_handler(CommandHandler("echo", echo_command))
    app.add_handler(CommandHandler("stats", stats_command))

    # Natural language fallback
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.COMMAND, handle_unknown))

    # Global error handler
    app.add_error_handler(_error_handler)

    return app
