# cogs/afk.py
from __future__ import annotations
import json
import time
from pathlib import Path
from typing import Dict, Any, List, Tuple

import discord
from discord import app_commands
from discord.ext import commands

DATA_DIR = Path("data")
STORE_FILE = DATA_DIR / "afk.json"

def _ensure_store():
    DATA_DIR.mkdir(exist_ok=True)
    if not STORE_FILE.exists():
        STORE_FILE.write_text(json.dumps({"guilds": {}}, indent=2), encoding="utf-8")

def _load_store() -> Dict[str, Any]:
    _ensure_store()
    try:
        return json.loads(STORE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"guilds": {}}

def _save_store(store: Dict[str, Any]) -> None:
    _ensure_store()
    STORE_FILE.write_text(json.dumps(store, indent=2), encoding="utf-8")

def _g(guild_id: int, store: Dict[str, Any]) -> Dict[str, Any]:
    gid = str(guild_id)
    store.setdefault("guilds", {})
    store["guilds"].setdefault(gid, {"afk": {}})  # user_id -> {reason, since}
    return store["guilds"][gid]

class AFK(commands.Cog):
    """AFK:
       - !afk(/afk) sets AFK (message stays)
       - Next non-command message clears AFK + sends welcome-back (auto-deletes 5s)
       - Mentioning AFK user posts reminder (stays)"""

    MENTION_COOLDOWN_S = 30

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.store = _load_store()
        self._recent_notices: Dict[Tuple[int, int], float] = {}

    @commands.hybrid_command(name="afk", description="Mark yourself AFK with an optional reason.")
    @app_commands.describe(reason="Reason for AFK")
    async def afk(self, ctx: commands.Context, *, reason: str = "No reason provided."):
        if ctx.guild is None:
            return
        gcfg = _g(ctx.guild.id, self.store)
        gcfg["afk"][str(ctx.author.id)] = {"reason": reason, "since": time.time()}
        _save_store(self.store)
        await ctx.send(f"💤 {ctx.author.mention} is now AFK: **{reason}**")  # stays

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        gcfg = _g(message.guild.id, self.store)

        # Don’t clear AFK on command messages (e.g., !afk)
        is_command = False
        try:
            prefixes = await self.bot.get_prefix(message)
            if isinstance(prefixes, str):
                prefixes = [prefixes]
            content = message.content or ""
            is_command = any(content.startswith(p) for p in prefixes if p)
        except Exception:
            pass

        # Clear AFK on first non-command message
        if str(message.author.id) in gcfg["afk"] and not is_command:
            gcfg["afk"].pop(str(message.author.id), None)
            _save_store(self.store)
            try:
                m = await message.channel.send(f"👋 Welcome back, {message.author.mention} — AFK removed.")
                await m.delete(delay=5)
            except discord.Forbidden:
                pass

        # AFK reminders for mentions (stays)
        to_notify: List[str] = []
        for target in message.mentions:
            if target.bot:
                continue
            data = gcfg["afk"].get(str(target.id))
            if not data:
                continue

            key = (message.author.id, target.id)
            now = time.time()
            if now - self._recent_notices.get(key, 0.0) < self.MENTION_COOLDOWN_S:
                continue
            self._recent_notices[key] = now

            reason = data.get("reason") or "No reason provided."
            since_ts = data.get("since")
            rel = f"<t:{int(since_ts)}:R>" if since_ts else "some time ago"
            to_notify.append(f"🛌 **{target.display_name}** is AFK (since {rel}): **{reason}**")

        if to_notify:
            try:
                await message.channel.send("\n".join(to_notify))  # no auto-delete
            except discord.Forbidden:
                pass

async def setup(bot: commands.Bot):
    await bot.add_cog(AFK(bot))