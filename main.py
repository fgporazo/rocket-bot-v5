# main.py
import os
import signal
import asyncio
import discord
from discord.ext import commands
from dotenv import load_dotenv
from helpers import init_db  # our SQLite helpers
from keep_alive import keep_alive  # optional for Replit/Railway

print("🚀 Running Bot Version: v4 - SQLite Ready!")

# ─── Kill ghost processes (Replit/Railway) ─────────────
try:
    os.kill(os.getpid() - 1, signal.SIGTERM)
except Exception:
    pass

# ─── Load environment ─────────────────────────────
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    print("❌ DISCORD_TOKEN not set in .env")
    exit(1)

# ─── Initialize database ─────────────────────────────
init_db()

# ─── Bot setup ─────────────────────────────
intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.messages = True
intents.message_content = True

bot = commands.Bot(command_prefix=".", intents=intents)

# ─── Landing message when joining a server ─────────────
@bot.event
async def on_guild_join(guild):
    channel = discord.utils.get(guild.text_channels, name="rocketbot")
    message = (
        "🚀 **Hey Rocket Players!**\n"
        "Thanks for letting me land—I promise I won’t crash your channel… at least not on purpose! 😎\n"
        "Type `.tr help` to unleash commands, boosts, and a little controlled **chaos**. Bwahahahaha! Let’s blast off! 🚀"
    )
    if channel and channel.permissions_for(guild.me).send_messages:
        await channel.send(message)
    else:
        for ch in guild.text_channels:
            if ch.permissions_for(guild.me).send_messages:
                await ch.send(message)
                break

# ─── Load all extensions from py folder ─────────────
async def load_extensions():
    extensions = [
        "py.rocket_slash_commands",
        "py.rocket_date_game",
        "py.rocket_campfire",
        "py.rocket_compatibility_test",
        "py.rocket_drawing_date",
        "py.rocket_escape_room",
        "py.rocket_secret_admirer",
        "py.rocket_mystery_date",
        "py.rocket_world_clock",
        "py.rocket_slash_news",
        "py.rocket_montage_challenge",
        "py.rocket_profile"
    ]
    for ext in extensions:
        try:
            await bot.load_extension(ext)
            print(f"✅ {ext} loaded")
        except Exception as e:
            print(f"❌ Failed to load {ext}: {e}")

# ─── Bot ready event ─────────────────────────────
@bot.event
async def on_ready():
    if bot.user:
        print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")
    else:
        print("❌ Bot user is None")
    try:
        await bot.tree.sync()
        print("✅ Slash commands synced globally")
    except Exception as e:
        print(f"❌ Failed to sync slash commands: {e}")

# ─── Start bot ─────────────────────────────
async def main():
    await load_extensions()
    try:
        await bot.start(TOKEN)
    except Exception as e:
        print(f"❌ Bot crashed: {e}")

# ─── Keep-alive for Replit/Railway ─────────────────────────────
keep_alive()  # Optional

# ─── Run bot ─────────────────────────────
asyncio.run(main())
