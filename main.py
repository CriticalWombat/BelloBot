import discord
import os
import asyncio
from dotenv import load_dotenv
from discord.ext import commands
from aiohttp import web
from scraper import get_analog_menu_image, get_coffee_classes

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

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    guild = discord.Object(id=SERVERID)
    bot.tree.copy_global_to(guild=guild)
    await bot.tree.sync(guild=guild)
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
    await interaction.followup.send(embed=embed)

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