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
intents.message_content = True  # needed for prefix commands

# ---------- bot ----------
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    log.info("✅ Logged in as %s (%s)", bot.user, bot.user.id)

@bot.event
async def setup_hook():
    """
    In discord.py v2, extensions with `async def setup(bot)` must be loaded with `await bot.load_extension`.
    We do that here, before syncing app commands.
    """
    cogs_dir = Path(__file__).parent / "cogs"
    for py in cogs_dir.glob("*.py"):
        ext = f"cogs.{py.stem}"
        try:
            await bot.load_extension(ext)
            log.info("🔹 Loaded cog: %s", ext)
        except Exception as e:
            log.exception("❌ Failed to load %s: %s", ext, e)

    # optional: sync slash commands (for your /ping and /userinfo)
    await bot.tree.sync()
    log.info("🗂️ Slash commands synced")

# ---------- run ----------
bot.run(TOKEN)