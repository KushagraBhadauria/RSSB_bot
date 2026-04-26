import gspread
from google.oauth2.service_account import Credentials
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
from datetime import datetime

# =============================================
TELEGRAM_TOKEN = "8623631025:AAHeZZMXh9Tg_g7NyypbrpGdBMT6PrJSBPU"
SHEET_NAME     = "AV Audio Equipment Area- KANPUR"
# =============================================

# Column mapping (1-based, as per Excel)
COL = {
    "sno"         : 1,
    "centre"      : 2,
    "type"        : 3,
    "amplifier"   : 4,
    "amp_builtin" : 5,
    "mixer"       : 6,
    "microphone"  : 7,
    "mic_stand_s" : 8,
    "mic_stand_b" : 9,
    "mike_lead"   : 10,
    "speaker"     : 11,
    "pen_drive"   : 12,
    "led_tv"      : 13,
    "battery"     : 15,
    "stage"       : 16,
    "remarks"     : 17,
    "last_updated": 18,
    "given_to"    : 19,
}

VALID_ITEMS = {
    "microphone"  : "Microphone",
    "mic_stand_s" : "Mic Stand (Small)",
    "mic_stand_b" : "Mic Stand (Big)",
    "mike_lead"   : "Mike Lead",
    "speaker"     : "Speaker",
    "pen_drive"   : "Pen Drive",
    "led_tv"      : "LED TV",
}


# ─────────────────────────────────────────
# SHEET
# ─────────────────────────────────────────
def get_sheet():
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    creds  = Credentials.from_service_account_file("credentials.json", scopes=scope)
    client = gspread.authorize(creds)
    return client.open(SHEET_NAME).sheet1


# ─────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────
def safe_num(val):
    try:
        v = str(val).strip().replace("----", "0").replace("---", "0").replace("nan", "0")
        return int(float(v)) if v else 0
    except:
        return None


def g(row, idx):
    """Get cell value safely by 1-based column index"""
    v = row[idx-1] if len(row) >= idx else ""
    s = str(v).strip()
    return s if s not in ["", "nan", "None"] else "—"


def parse_centres(all_rows):
    """
    Parse sheet rows into structured dict.
    Logic:
      - Main centre row: col A has a number (S.No), col B has centre name
      - BAAL SATSANG row: col A empty, col B empty, col C = 'BAAL SATSANG'
        and it immediately follows a main centre row

    Returns:
    {
      "ACHALDA": {
          "PARMARTHI": (sheet_row_num_1based, row_list),
      },
      "BHITERGAON": {
          "PARMARTHI":    (sheet_row_num_1based, row_list),
          "BAAL SATSANG": (sheet_row_num_1based, row_list),
      },
    }
    """
    centres      = {}
    current_name = None

    for i, row in enumerate(all_rows, start=1):  # i = 1-based sheet row number
        if i <= 6:  # skip header rows
            continue
        if len(row) < 3:
            continue

        sno   = str(row[0]).strip()
        name  = str(row[1]).strip()
        stype = str(row[2]).strip().upper()

        # Skip totally empty rows or legend rows at bottom
        if not stype or stype in ["CENTER", "SUB CENTER", "SATSANG POINT"]:
            current_name = None
            continue

        # Main centre row — S.No is a valid number AND name is non-empty
        is_main_row = False
        try:
            float(sno)
            if name and name.upper() not in ["NAN", ""]:
                is_main_row = True
        except ValueError:
            pass

        if is_main_row:
            current_name = name.upper()
            if current_name not in centres:
                centres[current_name] = {}
            centres[current_name][stype] = (i, list(row))
            continue

        # BAAL SATSANG row — S.No empty, name empty, type has BAAL, follows a centre
        if (not sno or sno in ["nan"]) and (not name or name in ["nan"]) \
                and "BAAL" in stype and current_name:
            centres[current_name][stype] = (i, list(row))
            # Don't reset current_name — only one BAAL row per centre
            continue

        # Any other non-empty row resets context
        if sno and name:
            current_name = None

    return centres


# ─────────────────────────────────────────
# BOT COMMANDS
# ─────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎙 Namaste! AV Equipment Tracker — Kanpur\n\n"
        "📋 Commands:\n\n"
        "/centres — Saare centres ki list\n\n"
        "/check ACHALDA — Centre ki poori detail\n\n"
        "/give ACHALDA microphone 2 Kushagra \n"
        "→ Equipment minus karo\n\n"
        "/return ACHALDA microphone 2\n"
        "→ Equipment wapas add karo\n\n"
        "/totalstock — Poore area ka total\n\n"
        "/help — Full guide"
    )


async def list_centres(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        sheet    = get_sheet()
        all_rows = sheet.get_all_values()
        data     = parse_centres(all_rows)

        lines = []
        for name, types in data.items():
            has_baal = any("BAAL" in t for t in types)
            tag      = " (P+B)" if has_baal else ""
            lines.append(f"• {name}{tag}")

        if not lines:
            await update.message.reply_text("Koi centre nahi mila!")
            return

        msg = (
            f"📍 All Centres — Kanpur ({len(lines)} total)\n"
            f"P+B = Parmarthi + Baal dono\n\n"
            + "\n".join(lines)
        )
        await update.message.reply_text(msg)

    except Exception as e:
        await update.message.reply_text(f"Error: {str(e)}")


def find_centre(data, centre_name):
    """Case-insensitive partial match"""
    search = centre_name.upper().strip()
    for key in data:
        if search == key:
            return key
    for key in data:
        if search in key:
            return key
    return None


async def check_centre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Centre ka naam do!\nExample: /check ACHALDA")
        return

    centre_name = " ".join(context.args).upper().strip()

    try:
        sheet    = get_sheet()
        all_rows = sheet.get_all_values()
        data     = parse_centres(all_rows)

        matched_key = find_centre(data, centre_name)
        if not matched_key:
            await update.message.reply_text(
                f"❌ '{centre_name}' nahi mila.\n/centres se list dekho."
            )
            return

        types    = data[matched_key]
        has_baal = any("BAAL" in t for t in types)

        if has_baal:
            header = (
                f"📍 {matched_key}\n"
                f"✅ PARMARTHI aur BAAL SATSANG dono hain.\n"
                f"{'═'*30}\n"
            )
        else:
            header = (
                f"📍 {matched_key}\n"
                f"ℹ️ Sirf PARMARTHI SATSANG hai.\n"
                f"{'═'*30}\n"
            )

        sections = []
        for stype, (_, row) in types.items():
            section = (
                f"\n🔹 {stype}\n"
                f"{'─'*26}\n"
                f"Amplifier       : {g(row, COL['amplifier'])} (Built-in: {g(row, COL['amp_builtin'])})\n"
                f"Mixer           : {g(row, COL['mixer'])}\n"
                f"Microphone      : {g(row, COL['microphone'])} nos\n"
                f"Mic Stand Small : {g(row, COL['mic_stand_s'])} nos\n"
                f"Mic Stand Big   : {g(row, COL['mic_stand_b'])} nos\n"
                f"Mike Lead       : {g(row, COL['mike_lead'])} nos\n"
                f"Speaker         : {g(row, COL['speaker'])} nos\n"
                f"Pen Drive       : {g(row, COL['pen_drive'])}\n"
                f"LED TV          : {g(row, COL['led_tv'])}\n"
                f"Battery Charger : {g(row, COL['battery'])}\n"
                f"Stage           : {g(row, COL['stage'])}\n"
                f"Remarks         : {g(row, COL['remarks'])}\n"
                f"Last Updated    : {g(row, COL['last_updated'])}\n"
                f"Given To        : {g(row, COL['given_to'])}\n"
            )
            sections.append(section)

        await update.message.reply_text(header + "".join(sections))

    except Exception as e:
        await update.message.reply_text(f"Error: {str(e)}")


async def give_equipment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 3:
        await update.message.reply_text(
            "Sahi format:\n"
            "/give <centre> <item> <qty> <person>\n\n"
            f"Valid items:\n{', '.join(VALID_ITEMS.keys())}\n\n"
            "Example:\n/give ACHALDA microphone 2 Kushagra "
        )
        return

    centre_name = context.args[0].upper()
    item        = context.args[1].lower()
    person      = " ".join(context.args[3:]) if len(context.args) > 3 else "Unknown"

    try:
        qty = int(context.args[2])
    except ValueError:
        await update.message.reply_text("Quantity number mein honi chahiye!")
        return

    if item not in VALID_ITEMS:
        await update.message.reply_text(
            f"❌ '{item}' valid nahi.\n\nValid items:\n{', '.join(VALID_ITEMS.keys())}"
        )
        return

    try:
        sheet       = get_sheet()
        all_rows    = sheet.get_all_values()
        data        = parse_centres(all_rows)
        matched_key = find_centre(data, centre_name)

        if not matched_key:
            await update.message.reply_text(f"❌ '{centre_name}' nahi mila.\n/centres se list dekho.")
            return

        types    = data[matched_key]
        has_baal = any("BAAL" in t for t in types)

        if has_baal:
            context.user_data["pending"] = {
                "action"     : "give",
                "centre_key" : matched_key,
                "item"       : item,
                "qty"        : qty,
                "person"     : person,
            }
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("PARMARTHI",    callback_data="stype|PARMARTHI")],
                [InlineKeyboardButton("BAAL SATSANG", callback_data="stype|BAAL SATSANG")],
            ])
            await update.message.reply_text(
                f"⚠️ '{matched_key}' mein PARMARTHI aur BAAL SATSANG dono hain.\n\n"
                f"Kis stock se {VALID_ITEMS[item]} dena hai?",
                reply_markup=keyboard,
            )
        else:
            # Only PARMARTHI — direct update
            row_num, row = types["PARMARTHI"]
            await _do_give(update.message, sheet, row_num, row,
                           item, qty, person, "PARMARTHI", matched_key)

    except Exception as e:
        await update.message.reply_text(f"Error: {str(e)}")


async def return_equipment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 3:
        await update.message.reply_text(
            "Sahi format:\n"
            "/return <centre> <item> <qty>\n\n"
            "Example:\n/return ACHALDA microphone 2"
        )
        return

    centre_name = context.args[0].upper()
    item        = context.args[1].lower()

    try:
        qty = int(context.args[2])
    except ValueError:
        await update.message.reply_text("Quantity number mein honi chahiye!")
        return

    if item not in VALID_ITEMS:
        await update.message.reply_text(
            f"❌ '{item}' valid nahi.\n\nValid items:\n{', '.join(VALID_ITEMS.keys())}"
        )
        return

    try:
        sheet       = get_sheet()
        all_rows    = sheet.get_all_values()
        data        = parse_centres(all_rows)
        matched_key = find_centre(data, centre_name)

        if not matched_key:
            await update.message.reply_text(f"❌ '{centre_name}' nahi mila.")
            return

        types    = data[matched_key]
        has_baal = any("BAAL" in t for t in types)

        if has_baal:
            context.user_data["pending"] = {
                "action"    : "return",
                "centre_key": matched_key,
                "item"      : item,
                "qty"       : qty,
            }
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("PARMARTHI",    callback_data="stype|PARMARTHI")],
                [InlineKeyboardButton("BAAL SATSANG", callback_data="stype|BAAL SATSANG")],
            ])
            await update.message.reply_text(
                f"⚠️ '{matched_key}' mein PARMARTHI aur BAAL SATSANG dono hain.\n\n"
                f"Kis stock mein {VALID_ITEMS[item]} wapas karna hai?",
                reply_markup=keyboard,
            )
        else:
            row_num, row = types["PARMARTHI"]
            await _do_return(update.message, sheet, row_num, row,
                             item, qty, "PARMARTHI", matched_key)

    except Exception as e:
        await update.message.reply_text(f"Error: {str(e)}")


async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not query.data.startswith("stype|"):
        return

    chosen_type = query.data.split("|")[1]
    pending     = context.user_data.get("pending")

    if not pending:
        await query.edit_message_text("Koi pending action nahi. Dobara /give ya /return use karo.")
        return

    try:
        sheet       = get_sheet()
        all_rows    = sheet.get_all_values()
        data        = parse_centres(all_rows)
        centre_key  = pending["centre_key"]
        types       = data.get(centre_key, {})

        # Match chosen type to actual key in types dict
        matched_stype = None
        for t in types:
            if chosen_type.upper() in t.upper():
                matched_stype = t
                break

        if not matched_stype:
            await query.edit_message_text(f"❌ '{chosen_type}' row nahi mili '{centre_key}' mein.")
            context.user_data.pop("pending", None)
            return

        row_num, row = types[matched_stype]

        if pending["action"] == "give":
            await _do_give(query, sheet, row_num, row,
                           pending["item"], pending["qty"],
                           pending.get("person", "Unknown"),
                           matched_stype, centre_key, edit=True)
        else:
            await _do_return(query, sheet, row_num, row,
                             pending["item"], pending["qty"],
                             matched_stype, centre_key, edit=True)

    except Exception as e:
        await query.edit_message_text(f"Error: {str(e)}")

    context.user_data.pop("pending", None)


async def _do_give(target, sheet, row_num, row, item, qty, person, stype, centre_name, edit=False):
    col_idx     = COL[item]
    current_val = row[col_idx - 1] if len(row) >= col_idx else "0"
    current_qty = safe_num(current_val)

    if current_qty is None:
        msg = f"❌ {VALID_ITEMS[item]} ki value '{current_val}' number nahi hai."
        await (target.edit_message_text(msg) if edit else target.reply_text(msg))
        return

    if qty > current_qty:
        msg = (
            f"❌ Stock nahi!\n"
            f"{centre_name} ({stype}) mein {VALID_ITEMS[item]} sirf {current_qty} hain."
        )
        await (target.edit_message_text(msg) if edit else target.reply_text(msg))
        return

    new_qty = current_qty - qty
    today   = datetime.now().strftime("%d-%b-%Y %I:%M %p")

    sheet.update_cell(row_num, col_idx,            new_qty)
    sheet.update_cell(row_num, COL["last_updated"], today)
    sheet.update_cell(row_num, COL["given_to"],     f"{person} ({stype})")

    msg = (
        f"✅ Done!\n\n"
        f"Centre  : {centre_name}\n"
        f"Satsang : {stype}\n"
        f"Item    : {VALID_ITEMS[item]}\n"
        f"Pehle   : {current_qty}\n"
        f"Diya    : {qty}\n"
        f"Bacha   : {new_qty}\n"
        f"Kise    : {person}\n"
        f"Date    : {today}"
    )
    await (target.edit_message_text(msg) if edit else target.reply_text(msg))


async def _do_return(target, sheet, row_num, row, item, qty, stype, centre_name, edit=False):
    col_idx     = COL[item]
    current_val = row[col_idx - 1] if len(row) >= col_idx else "0"
    current_qty = safe_num(current_val)

    if current_qty is None:
        msg = f"❌ {VALID_ITEMS[item]} ki value number nahi hai."
        await (target.edit_message_text(msg) if edit else target.reply_text(msg))
        return

    new_qty = current_qty + qty
    today   = datetime.now().strftime("%d-%b-%Y %I:%M %p")

    sheet.update_cell(row_num, col_idx,            new_qty)
    sheet.update_cell(row_num, COL["last_updated"], today)

    msg = (
        f"✅ Wapas Mila!\n\n"
        f"Centre  : {centre_name}\n"
        f"Satsang : {stype}\n"
        f"Item    : {VALID_ITEMS[item]}\n"
        f"Pehle   : {current_qty}\n"
        f"Aaya    : {qty}\n"
        f"Ab hai  : {new_qty}\n"
        f"Date    : {today}"
    )
    await (target.edit_message_text(msg) if edit else target.reply_text(msg))


async def total_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        sheet    = get_sheet()
        all_rows = sheet.get_all_values()
        data     = parse_centres(all_rows)

        totals = {k: 0 for k in VALID_ITEMS}

        for centre, types in data.items():
            for stype, (_, row) in types.items():
                for item in VALID_ITEMS:
                    col = COL[item]
                    val = safe_num(row[col-1] if len(row) >= col else 0)
                    if val is not None:
                        totals[item] += val

        msg = "📊 Total Stock — Kanpur Area\n" + "═"*28 + "\n"
        for item, label in VALID_ITEMS.items():
            msg += f"{label:<22}: {totals[item]}\n"

        await update.message.reply_text(msg)

    except Exception as e:
        await update.message.reply_text(f"Error: {str(e)}")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 Full Guide:\n\n"
        "/centres\n→ Saare centres (P+B = Parmarthi+Baal dono)\n\n"
        "/check ACHALDA\n→ Centre ki poori detail\n\n"
        "/give ACHALDA microphone 2 Kushagra \n→ Mic -2, Kushagra  ko diya\n"
        "  BAAL bhi hai toh button aayega\n\n"
        "/return ACHALDA microphone 2\n→ Mic +2 wapas aayi\n\n"
        "/totalstock\n→ Poore area ka total stock\n\n"
        f"Valid items:\n{', '.join(VALID_ITEMS.keys())}"
    )


# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start",      start))
    app.add_handler(CommandHandler("centres",    list_centres))
    app.add_handler(CommandHandler("check",      check_centre))
    app.add_handler(CommandHandler("give",       give_equipment))
    app.add_handler(CommandHandler("return",     return_equipment))
    app.add_handler(CommandHandler("totalstock", total_stock))
    app.add_handler(CommandHandler("help",       help_command))
    app.add_handler(CallbackQueryHandler(handle_button))

    print("✅ Bot chal raha hai...")
    app.run_polling()


if __name__ == "__main__":
    main()
