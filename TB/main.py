# main.py
import os
import logging
from pathlib import Path
import inspect

import discord
from discord.ext import commands
from dotenv import load_dotenv

# ---------- env ----------
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("❌ No DISCORD_TOKEN found in .env file!")

# ---------- logging ----------
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("bot")

# ---------- intents ----------
intents = discord.Intents.default()
intents.message_content = True   # needed for prefix commands / on_message
intents.members = True           # for staffboard (roles)
intents.presences = True         # for status bubbles

# single Bot instance
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def setup_hook():
    """
    In discord.py v2, extensions with `async def setup(bot)` must be loaded via `await bot.load_extension`.
    Load cogs here. We do NOT global-sync here; we do fast per-guild sync in on_ready.
    """
    cogs_dir = Path(__file__).parent / "cogs"
    for py in cogs_dir.glob("*.py"):
        ext = f"cogs.{py.stem}"
        try:
            await bot.load_extension(ext)
            log.info("🔹 Loaded cog: %s", ext)
        except Exception as e:
            log.exception("❌ Failed to load %s: %s", ext, e)

@bot.event
async def on_ready():
    log.info("✅ Logged in as %s (%s)", bot.user, bot.user.id)

    # --- Per-guild slash command sync for instant availability ---
    synced = 0
    failed = 0
    for g in bot.guilds:
        try:
            await bot.tree.sync(guild=discord.Object(id=g.id))
            synced += 1
        except Exception as e:
            failed += 1
# main.py
import os
import logging
from pathlib import Path

import discord
from discord.ext import commands
from dotenv import load_dotenv

# ---------- env ----------
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("❌ No DISCORD_TOKEN found in .env file!")

# ---------- logging ----------
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("bot")

# ---------- intents ----------
intents = discord.Intents.default()
intents.message_content = True   # needed for prefix commands / on_message
intents.members = True           # for staffboard (roles)
intents.presences = True         # for status bubbles

# ---------- bot ----------
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def setup_hook():
    """
    In discord.py v2, extensions with `async def setup(bot)` must be loaded with `await bot.load_extension`.
    We do that here, then sync app commands globally.
    """
    cogs_dir = Path(__file__).parent / "cogs"
    for py in cogs_dir.glob("*.py"):
        ext = f"cogs.{py.stem}"
        try:
            await bot.load_extension(ext)
            log.info("🔹 Loaded cog: %s", ext)
        except Exception as e:
            log.exception("❌ Failed to load %s: %s", ext, e)

    # Global sync (may take a minute to propagate across all guilds)
    await bot.tree.sync()
    log.info("🗂️ Slash commands synced globally")

@bot.event
async def on_ready():
    log.info("✅ Logged in as %s (%s)", bot.user, bot.user.id)

# ---------- run ----------
bot.run(TOKEN)