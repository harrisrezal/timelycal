import asyncio
import os
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
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
SELECT_DAY, SELECT_STATION, SELECT_DIRECTION, SELECT_USE_SAVED = range(4)


# ── /next Guided Menu ─────────────────────────────────────────────────────────

CANCEL_BTN = InlineKeyboardButton("Cancel", callback_data="cancel")

HELP_TEXT = (
    "I'm TimelyCal — ask me anything about the Caltrain schedule!\n\n"
    "Examples:\n"
    "• What time is the next train from SF to San Jose?\n"
    "• When is the last train on weekends?\n"
    "• How long does it take from Millbrae to Palo Alto?\n\n"
    "Commands:\n"
    "/next       - Next 3 trains from a station\n"
    "/schedule   - Full day timetable for a station\n"
    "/mystation  - View or change your saved station\n"
    "/help       - Show this message"
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
    from services.schedule import get_next_trains

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
            lines.append(f"Train {t['train']} — {t['time_str']} (in {diff} mins)")
        return "\n".join(lines)

    sf_trains = format_trains("sf")
    sj_trains = format_trains("sj")

    text = (
        f"📍 {station}\n"
        f"🗓 {date_str} | {time_str} ({day_label})\n\n"
        f"➡️ Towards San Francisco\n{sf_trains}\n\n"
        f"➡️ Towards San Jose\n{sj_trains}\n\n"
        "⚠️ Schedule-based only. Not real-time."
    )

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
    from services.schedule import get_all_trains
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
        rows = "\n".join(f"Train {t['train']} — {t['time_str']}" for t in items)
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
    if _is_cold_start():
        await update.message.reply_text(
            "⏳ Server just woke up from idle — first response may take ~10 seconds."
        )
    user = update.effective_user
    await update.message.reply_text(
        f"Hello {user.first_name}! I'm TimelyCal, your Caltrain assistant.\n\n"
        "Just type any question about the schedule, or use the commands:\n"
        "• /next for the next 3 trains from a station\n"
        "• /schedule for the full day timetable\n"
        "• /mystation to view or change your saved station\n\n"
        "Use /help to see more options."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if _is_cold_start():
        await update.message.reply_text(
            "⏳ Server just woke up from idle — first response may take ~10 seconds."
        )
    await update.message.reply_text(HELP_TEXT)


async def mystation_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import pytz
    from datetime import datetime
    from services.user_prefs import get_preference
    from services.schedule import get_next_trains, STATIONS


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
            lines.append(f"Train {t['train']} — {t['time_str']} (in {diff} mins)")
        return "\n".join(lines)

    sf_trains = format_trains("sf")
    sj_trains = format_trains("sj")

    text = (
        f"📍 {station}\n"
        f"🗓 {date_str} | {time_str} ({day_label})\n\n"
        f"➡️ Towards San Francisco\n{sf_trains}\n\n"
        f"➡️ Towards San Jose\n{sj_trains}\n\n"
        "⚠️ Schedule-based only. Not real-time."
    )

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
    task = asyncio.create_task(asyncio.to_thread(query, text))

    done, _ = await asyncio.wait([task], timeout=2.0)
    if not done:
        await update.message.reply_text("⏳ Still searching, please wait a moment...")

    answer = await task
    await update.message.reply_text(answer)


async def handle_unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Sorry, I don't know that command. Use /help for options."
    )


# ── Application Builder ───────────────────────────────────────────────────────

def get_application() -> Application:
    """Build and return the Telegram Application with all handlers registered."""
    app = Application.builder().token(BOT_TOKEN).build()

    # Guided schedule menu (ConversationHandler — must be registered before plain handlers)
    cancel_handler = CallbackQueryHandler(_cancel_callback, pattern="^cancel$")

    schedule_conv = ConversationHandler(
        entry_points=[CommandHandler("next", ask_day_type)],
        states={
            SELECT_STATION: [cancel_handler, CallbackQueryHandler(show_both_directions, pattern="^sta:")],
        },
        fallbacks=[CommandHandler("cancel", cancel_schedule)],
        allow_reentry=True,
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
        },
        fallbacks=[CommandHandler("cancel", cancel_schedule)],
        allow_reentry=True,
    )
    app.add_handler(timing_conv)

    # Standalone preference callbacks (outside ConversationHandlers)
    app.add_handler(CallbackQueryHandler(save_station_callback, pattern="^save_station:"))
    app.add_handler(CallbackQueryHandler(mystation_change_callback, pattern="^mystation_change$"))
    app.add_handler(CallbackQueryHandler(mystation_set_callback, pattern="^mset:"))
    app.add_handler(CallbackQueryHandler(mystation_clear_callback, pattern="^mystation_clear$"))

    # Standard command handlers
    app.add_handler(CommandHandler("ask", ask_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("mystation", mystation_command))
    app.add_handler(CommandHandler("echo", echo_command))

    # Natural language fallback
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.COMMAND, handle_unknown))

    return app
