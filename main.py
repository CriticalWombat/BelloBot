import discord
import os
import asyncio
import time
from dotenv import load_dotenv
from discord import app_commands
from discord.ext import commands
from aiohttp import web
from scraper import get_analog_menu_image, get_coffee_classes
from menuOCR import extract_menu_text, parse_menu_items, format_menu
from votes import cast_vote, add_note, get_active_results, get_archived_sessions, get_active_items

load_dotenv()
TOKEN = os.getenv("TOKEN")
SERVERID = int(os.getenv("SERVERID"))
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

EXPECTED_PAYLOAD = {
    "source": "home_assistant",
    "event": "loc-ping"
}

# ---------------------------------------------------------------------------
# Menu item cache — avoids running OCR on every autocomplete keypress
# ---------------------------------------------------------------------------
_menu_cache: dict = {"ts": 0.0, "items": []}
_CACHE_TTL = 3600  # seconds


async def get_menu_items() -> list[str]:
    """
    Return current Analog Bar drink names.  Uses a 1-hour in-memory cache.
    Falls back to the active vote session's item list if the network is down.
    On first call after a cold restart, seeds from the on-disk vote session
    so autocomplete works immediately without an OCR round-trip.
    """
    now = time.monotonic()
    if _menu_cache["items"] and now - _menu_cache["ts"] < _CACHE_TTL:
        return _menu_cache["items"]

    loop = asyncio.get_running_loop()
    try:
        url = await loop.run_in_executor(None, get_analog_menu_image)
        if url:
            raw_text = await loop.run_in_executor(None, extract_menu_text, url)
            parsed = parse_menu_items(raw_text)
            names = [item["name"] for item in parsed if item["name"]]
            if names:
                _menu_cache["ts"] = now
                _menu_cache["items"] = names
    except Exception:
        pass

    return _menu_cache["items"]

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    guild = discord.Object(id=SERVERID)
    bot.tree.copy_global_to(guild=guild)
    await bot.tree.sync(guild=guild)
    # Seed from disk immediately so autocomplete works before the OCR fetch completes
    saved = get_active_items()
    if saved:
        _menu_cache["items"] = saved
        _menu_cache["ts"] = time.monotonic()
    # Refresh from the live menu in the background regardless
    asyncio.create_task(get_menu_items())
    print("Synced and Ready!")

@bot.tree.command(name="reserve", description="Reserve seats at the Analog Bar!")
async def reserve(interaction: discord.Interaction):
    embed = discord.Embed(
        title="Reserve a seat at the Analog Bar!",
        description="Click the title above to book your spot!",
        url="https://carabellocoffee.resurva.com/",
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="analog", description="Show the Analog Bar menu this month")
async def analog_menu(interaction: discord.Interaction):
    await interaction.response.defer()

    loop = asyncio.get_running_loop()
    menu = await loop.run_in_executor(None, get_analog_menu_image)

    if not menu:
        await interaction.followup.send("Couldn't fetch the menu right now.")
        return

    embed = discord.Embed(title="Analog Bar Menu", color=discord.Color.green())
    embed.set_image(url=menu)

    try:
        raw_text = await loop.run_in_executor(None, extract_menu_text, menu)
        items = parse_menu_items(raw_text)
        menu_text = format_menu(items) if items else raw_text
        if menu_text:
            embed.description = menu_text[:4096]
    except Exception:
        pass  # OCR failed; still show the image

    await interaction.followup.send(embed=embed)

async def vote_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    items = await get_menu_items()
    return [
        app_commands.Choice(name=name, value=name)
        for name in items
        if current.lower() in name.lower()
    ][:25]


def _build_session_embed(session: dict, active: bool) -> discord.Embed:
    """
    Build an embed for a session showing votes (with voters) and any notes.
    Used by /results, /votehistory, and /notes.
    """
    medals = ["🥇", "🥈", "🥉"]
    started = session["started_at"][:10]
    if active:
        title = f"Current Menu — Menu #{session['id']} (since {started})"
        color = discord.Color.green()
    else:
        ended = session["ended_at"][:10]
        title = f"Menu #{session['id']}  ({started} → {ended})"
        color = discord.Color.blurple()

    embed = discord.Embed(title=title, color=color)

    # --- Votes section ---
    sorted_votes = sorted(
        session["votes"].items(), key=lambda x: len(x[1]), reverse=True
    )
    vote_fields = 0
    for i, (drink, voters) in enumerate(sorted_votes):
        count = len(voters)
        if count == 0:
            continue
        medal = medals[i] if i < len(medals) else f"`{i + 1}.`"
        names = list(voters.values())
        voter_str = ", ".join(names[:10])
        if len(names) > 10:
            voter_str += f" *+{len(names) - 10} more*"
        embed.add_field(
            name=f"{medal} {drink} — {count} vote{'s' if count != 1 else ''}",
            value=voter_str,
            inline=False,
        )
        vote_fields += 1

    if vote_fields == 0:
        embed.add_field(name="Votes", value="No votes recorded.", inline=False)

    # --- Notes section ---
    notes = session.get("notes", {})
    noted_drinks = [(drink, entries) for drink, entries in notes.items() if entries]
    if noted_drinks:
        embed.add_field(name="​", value="**📝 Notes**", inline=False)
        for drink, entries in noted_drinks:
            lines = []
            for entry in entries:
                date = entry["timestamp"][:10]
                lines.append(f"• {entry['text']} — *{entry['user_name']}, {date}*")
            embed.add_field(
                name=drink,
                value="\n".join(lines)[:1024],
                inline=False,
            )

    return embed


def _build_notes_embed(session: dict, active: bool) -> discord.Embed:
    """
    Build a notes-focused embed showing every menu item, with notes where they
    exist.  Used by /notes (current menu) and the notes view in /votehistory.
    """
    started = session["started_at"][:10]
    if active:
        title = f"📝 Current Menu Notes — Menu #{session['id']} (since {started})"
        color = discord.Color.green()
    else:
        ended = session["ended_at"][:10]
        title = f"📝 Menu #{session['id']} Notes  ({started} → {ended})"
        color = discord.Color.blurple()

    embed = discord.Embed(title=title, color=color)
    notes = session.get("notes", {})
    items = session.get("items", list(notes.keys()))

    for drink in items:
        entries = notes.get(drink, [])
        if entries:
            lines = []
            for entry in entries:
                date = entry["timestamp"][:10]
                lines.append(f"• {entry['text']} — *{entry['user_name']}, {date}*")
            value = "\n".join(lines)[:1024]
        else:
            value = "*(no notes yet)*"
        embed.add_field(name=drink, value=value, inline=False)

    if not embed.fields:
        embed.description = "No menu items found."
    return embed


@bot.tree.command(name="vote", description="Vote for your favorite Analog Bar drink this month!")
@app_commands.autocomplete(drink=vote_autocomplete)
async def vote(interaction: discord.Interaction, drink: str):
    items = await get_menu_items()
    if not items:
        await interaction.response.send_message(
            "Couldn't load the menu right now — try again shortly.", ephemeral=True
        )
        return
    if drink not in items:
        await interaction.response.send_message(
            f"**{drink}** isn't on the current menu. Pick from the autocomplete list.",
            ephemeral=True,
        )
        return

    user_id = str(interaction.user.id)
    user_name = interaction.user.display_name
    count, new_session = cast_vote(drink, items, user_id, user_name)

    if count is None:
        await interaction.response.send_message(
            "You've already voted this menu cycle — one vote per person!", ephemeral=True
        )
        return

    msg = f"Voted for **{drink}**! It now has **{count}** vote{'s' if count != 1 else ''}."
    if new_session:
        msg += "\n*(The menu changed — a fresh tally has been started and the old results are archived.)*"
    await interaction.response.send_message(msg)


@bot.tree.command(name="results", description="Show vote tallies for the current Analog Bar menu")
async def results(interaction: discord.Interaction):
    session = get_active_results()
    if not session or not any(session["votes"].values()):
        await interaction.response.send_message(
            "No votes have been cast yet — be the first with `/vote`!", ephemeral=True
        )
        return

    await interaction.response.send_message(embed=_build_session_embed(session, active=True))


@bot.tree.command(name="votehistory", description="Show voting results from past Analog Bar menus")
async def votehistory(interaction: discord.Interaction):
    archived = get_archived_sessions()
    if not archived:
        await interaction.response.send_message(
            "No archived menus yet — history builds up as menus change.", ephemeral=True
        )
        return

    embeds = [_build_session_embed(s, active=False) for s in reversed(archived)]
    await interaction.response.send_message(embeds=embeds[:10])


@bot.tree.command(name="add_note", description="Leave a note on an Analog Bar drink")
@app_commands.describe(drink="The drink to annotate", note="Your note (max 500 characters)")
@app_commands.autocomplete(drink=vote_autocomplete)
async def add_note_cmd(interaction: discord.Interaction, drink: str, note: str):
    if len(note) > 500:
        await interaction.response.send_message(
            "Notes are capped at 500 characters — please trim yours a bit.", ephemeral=True
        )
        return

    items = await get_menu_items()
    if not items:
        await interaction.response.send_message(
            "Couldn't load the menu right now — try again shortly.", ephemeral=True
        )
        return
    if drink not in items:
        await interaction.response.send_message(
            f"**{drink}** isn't on the current menu. Pick from the autocomplete list.",
            ephemeral=True,
        )
        return

    user_id = str(interaction.user.id)
    user_name = interaction.user.display_name
    new_session = add_note(drink, items, user_id, user_name, note)

    msg = f"📝 Note added to **{drink}**!"
    if new_session:
        msg += "\n*(The menu changed — a fresh session has started and the old one is archived.)*"
    await interaction.response.send_message(msg)


@bot.tree.command(name="notes", description="Show all notes left on the current Analog Bar menu")
async def notes_cmd(interaction: discord.Interaction):
    session = get_active_results()
    if not session:
        await interaction.response.send_message(
            "No menu session yet — use `/vote` or `/add_note` to get started.", ephemeral=True
        )
        return

    await interaction.response.send_message(embed=_build_notes_embed(session, active=True))


@bot.tree.command(name="events", description="Show upcoming Carabello coffee classes")
async def events(interaction: discord.Interaction):
    await interaction.response.defer()

    loop = asyncio.get_running_loop()
    classes = await loop.run_in_executor(None, get_coffee_classes)

    if not classes:
        await interaction.followup.send("No upcoming events found.")
        return

    embeds = []
    seen_urls = {}

    for event in classes:
        url = event["image_url"]
        seen_urls[url] = seen_urls.get(url, 0) + 1
        if seen_urls[url] > 1:
            url = f"{url}?v={seen_urls[url]}"

        embed = discord.Embed(
            title=event["date"],
            url=event["ticket_url"],
            color=discord.Color.green()
        )
        embed.set_image(url=url)
        embeds.append(embed)

    await interaction.followup.send(embeds=embeds[:10])

async def handle_webhook(request):
    secret = request.headers.get("X-Webhook-Secret")
    if secret != WEBHOOK_SECRET:
        return web.Response(status=401, text="Unauthorized")

    data = await request.json()

    if data.get("source") != EXPECTED_PAYLOAD["source"] or \
       data.get("event") != EXPECTED_PAYLOAD["event"]:
        return web.Response(status=400, text="Unrecognized payload")

    person = data.get("person", "Someone")
    channel = bot.get_channel(CHANNEL_ID)
    await channel.send(f"@here {person} is at Carabello!")

    return web.Response(text="OK")

async def start_webserver():
    app = web.Application()
    app.router.add_post("/webhook", handle_webhook)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()
    print("Webhook listener running on port 8080")

async def main():
    await start_webserver()
    await bot.start(TOKEN)

asyncio.run(main())