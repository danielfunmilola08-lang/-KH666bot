import os
import html
import logging
from datetime import datetime

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("football-bot")

BOT_TOKEN = os.environ["BOT_TOKEN"]
API_KEY = os.environ["FOOTBALL_API_KEY"]
BASE = "https://api.football-data.org/v4"

LEAGUES = {
    "PL": "🏴 Premier League",
    "PD": "🇪🇸 La Liga",
    "SA": "🇮🇹 Serie A",
    "BL1": "🇩🇪 Bundesliga",
    "FL1": "🇫🇷 Ligue 1",
    "CL": "🏆 Champions League",
}


async def api(path: str) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(BASE + path, headers={"X-Auth-Token": API_KEY})
        r.raise_for_status()
        return r.json()


def league_menu() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(name, callback_data=f"lg:{code}")]
        for code, name in LEAGUES.items()
    ]
    return InlineKeyboardMarkup(rows)


def action_menu(code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("📊 Table", callback_data=f"act:{code}:table"),
                InlineKeyboardButton("⚽ Scorers", callback_data=f"act:{code}:scorers"),
            ],
            [
                InlineKeyboardButton("📅 Fixtures", callback_data=f"act:{code}:fixtures"),
                InlineKeyboardButton("✅ Results", callback_data=f"act:{code}:results"),
            ],
            [InlineKeyboardButton("⬅️ Leagues", callback_data="home")],
        ]
    )


async def get_table(code: str) -> str:
    data = await api(f"/competitions/{code}/standings")
    table = data["standings"][0]["table"]
    lines = ["#  Team  P  W  D  L Pts"]
    for t in table:
        lines.append(
            f"{t['position']:>2} {(t['team'].get('tla') or '???'):<4}"
            f"{t['playedGames']:>2} {t['won']:>2} {t['draw']:>2} {t['lost']:>2} {t['points']:>3}"
        )
    return f"<b>{LEAGUES[code]} – Table</b>\n<pre>{html.escape(chr(10).join(lines))}</pre>"


async def get_scorers(code: str) -> str:
    data = await api(f"/competitions/{code}/scorers?limit=10")
    lines = []
    for i, s in enumerate(data["scorers"], 1):
        assists = s.get("assists") or 0
        lines.append(
            f"{i}. {html.escape(s['player']['name'])} "
            f"({html.escape(s['team'].get('tla') or '')}) – "
            f"{s['goals']} goals, {assists} ast"
        )
    return f"<b>{LEAGUES[code]} – Top scorers</b>\n\n" + "\n".join(lines)


def fmt_date(iso: str) -> str:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%d %b %H:%M UTC")


async def get_fixtures(code: str) -> str:
    data = await api(f"/competitions/{code}/matches?status=SCHEDULED,TIMED")
    matches = data["matches"][:10]
    if not matches:
        return "No upcoming fixtures."
    lines = [
        f"{fmt_date(m['utcDate'])}\n  {html.escape(m['homeTeam']['name'])} vs {html.escape(m['awayTeam']['name'])}"
        for m in matches
    ]
    return f"<b>{LEAGUES[code]} – Fixtures</b>\n\n" + "\n".join(lines)


async def get_results(code: str) -> str:
    data = await api(f"/competitions/{code}/matches?status=FINISHED")
    matches = data["matches"][-10:][::-1]
    if not matches:
        return "No results yet."
    lines = []
    for m in matches:
        ft = m["score"]["fullTime"]
        lines.append(
            f"{html.escape(m['homeTeam']['name'])} {ft['home']}–{ft['away']} "
            f"{html.escape(m['awayTeam']['name'])}"
        )
    return f"<b>{LEAGUES[code]} – Results</b>\n\n" + "\n".join(lines)


ACTIONS = {
    "table": get_table,
    "scorers": get_scorers,
    "fixtures": get_fixtures,
    "results": get_results,
}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = html.escape(update.effective_user.first_name or "there")
    await update.message.reply_text(
        f"👋 Hi {name}! Welcome to <b>Football Stats</b>.\nPick a league:",
        parse_mode=ParseMode.HTML,
        reply_markup=league_menu(),
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Use /start to open the league menu.")


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    parts = q.data.split(":")

    if parts[0] == "home":
        await q.edit_message_text("Pick a league:", reply_markup=league_menu())
    elif parts[0] == "lg":
        code = parts[1]
        await q.edit_message_text(
            f"<b>{LEAGUES[code]}</b>\nWhat do you want to see?",
            parse_mode=ParseMode.HTML,
            reply_markup=action_menu(code),
        )
    elif parts[0] == "act":
        _, code, action = parts
        try:
            text = await ACTIONS[action](code)
        except httpx.HTTPStatusError as e:
            log.warning("API error: %s", e)
            text = (
                "⏳ Too many requests, try again in a minute."
                if e.response.status_code == 429
                else "⚠️ Couldn't fetch data right now."
            )
        except Exception:
            log.exception("Unexpected error")
            text = "⚠️ Something went wrong."
        await q.edit_message_text(
            text, parse_mode=ParseMode.HTML, reply_markup=action_menu(code)
        )


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CallbackQueryHandler(on_button))
    log.info("Bot running...")
    app.run_polling()


if __name__ == "__main__":
    main()
