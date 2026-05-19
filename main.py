import discord
import os
import requests
import asyncio
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from discord.ext import commands

load_dotenv()
TOKEN = os.getenv("TOKEN")
ServerID=os.getenv("SERVERID")
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}

def fetch_soup(url):
    response = requests.get(url, headers=HEADERS)
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")

def shgcdn_url(img):
    src = img.get("src", "")
    if "shgcdn.com" not in src:
        return src
    uuid = src.split("shgcdn.com/")[1].split("/")[0]
    return f"https://i.shgcdn.com/{uuid}/-/format/auto/-/quality/normal/-/resize/1200x/"

def get_analog_menu_image():
    soup = fetch_soup("https://www.carabellocoffee.com/pages/analog")
    container = soup.find("div", class_="shg-image-overflow")
    img = container.find("img") if container else None
    return shgcdn_url(img) if img else None

def get_coffee_classes():
    soup = fetch_soup("https://www.carabellocoffee.com/collections/coffee-classes")
    events = []
    for link in soup.find_all("a", class_="shogun-image-link"):
        img = link.find("img")
        date_div = link.find_next("div", class_="shg-rich-text")
        if img:
            events.append({
                "date": date_div.get_text(strip=True) if date_div else "Date TBD",
                "image_url": shgcdn_url(img),
                "ticket_url": link.get("href", "")
            })
    return events

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    guild = discord.Object(id=ServerID)
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
    await interaction.response.defer()  # gives you more time if scraping is slow

    loop = asyncio.get_event_loop()
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

    loop = asyncio.get_event_loop()
    classes = await loop.run_in_executor(None, get_coffee_classes)

    if not classes:
        await interaction.followup.send("No upcoming events found.")
        return

    embeds = []
    seen_urls = {}

    for event in classes:
        url = event["image_url"]

        # Track how many times we've seen this URL
        seen_urls[url] = seen_urls.get(url, 0) + 1
        if seen_urls[url] > 1:
            # Append a dummy query param to make it unique (Otherwise discord won't load the image)
            url = f"{url}?v={seen_urls[url]}"

        embed = discord.Embed(
            title=event["date"],
            url=event["ticket_url"],
            color=discord.Color.green()
        )
        embed.set_image(url=url)
        embeds.append(embed)

    await interaction.followup.send(embeds=embeds[:10])


bot.run(TOKEN)