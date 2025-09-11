# cogs/afk.py
from __future__ import annotations
from typing import Optional, Dict, Tuple
import asyncio
import time
import discord
from discord.ext import commands

class AFK(commands.Cog):
    """
    Simple AFK system:
    - /afk [reason] or !afk [reason] to set AFK
    - Auto clears when user sends a message (or use /back, !back)
    - Mentions of AFK users get a notice (rate-limited)
    """

    # how often we can remind the same author about the same AFK target (seconds)
    MENTION_COOLDOWN_S = 30

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # user_id -> data
        self.afk: Dict[int, Dict[str, Optional[str]]] = {}
        # (mentioner_id, target_id) -> last_notified_ts
        self._recent_notices: Dict[Tuple[int, int], float] = {}

    # ------------- Commands -------------

    @commands.hybrid_command(name="afk", description="Set your AFK with an optional reason.")
    async def afk(self, ctx: commands.Context, *, reason: Optional[str] = None):
        user = ctx.author
        now = discord.utils.utcnow()
        entry = self.afk.get(user.id, {})

        # Try to tag nickname with [AFK]
        old_nick = entry.get("old_nick") if entry else None
        if old_nick is None and isinstance(user, discord.Member):
            old_nick = user.nick
            try:
                display = user.display_name
                if not display.startswith("[AFK]"):
                    await user.edit(nick=f"[AFK] {display}")
            except (discord.Forbidden, discord.HTTPException):
                pass  # ignore if we can't change nick

        self.afk[user.id] = {
            "since": now.isoformat(),
            "reason": reason or "",
            "old_nick": old_nick,
        }

        msg = f"🛌 {user.mention} is now AFK."
        if reason:
            msg += f" Reason: **{reason}**"
        await ctx.reply(msg, mention_author=False)

    @commands.hybrid_command(name="back", description="Clear your AFK status.")
    async def back(self, ctx: commands.Context):
        await self._clear_afk(ctx.author, announce_channel=ctx.channel)

    @commands.hybrid_command(name="afkstatus", description="Check if a user is AFK.")
    async def afkstatus(self, ctx: commands.Context, member: Optional[discord.Member] = None):
        member = member or ctx.author
        data = self.afk.get(member.id)
        if not data:
            await ctx.reply(f"✅ {member.mention} is **not AFK**.", mention_author=False)
            return

        since = data.get("since")
        reason = data.get("reason") or "No reason provided."
        # Try a friendly relative time
        try:
            dt = discord.utils.parse_time(since)
            rel = discord.utils.format_dt(dt, style="R") if dt else "some time ago"
        except Exception:
            rel = "some time ago"

        await ctx.reply(
            f"🛌 {member.mention} has been AFK since {rel}. Reason: **{reason}**",
            mention_author=False,
        )

    # ------------- Listeners -------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # ignore bots and DMs
        if message.author.bot or message.guild is None:
            return

        # If the AFK user speaks, clear their AFK
        if message.author.id in self.afk:
            await self._clear_afk(message.author, announce_channel=message.channel)

        # Notify when mentioning AFK users
        if message.mentions:
            await self._handle_mentions(message)

    # ------------- Helpers -------------

    async def _clear_afk(self, member: discord.abc.User, announce_channel: Optional[discord.abc.Messageable] = None):
        data = self.afk.pop(member.id, None)
        if not data:
            return

        # Restore nickname if we changed it
        if isinstance(member, discord.Member):
            old = data.get("old_nick", None)
            try:
                # Only revert if current nick starts with [AFK]
                if member.guild and member.nick and member.nick.startswith("[AFK]"):
                    await member.edit(nick=old)
            except (discord.Forbidden, discord.HTTPException):
                pass

        if announce_channel:
            try:
                await announce_channel.send(f"👋 {member.mention} is **no longer AFK**.")
            except discord.Forbidden:
                pass

    async def _handle_mentions(self, message: discord.Message):
        channel = message.channel
        author = message.author
        to_notify = []

        for target in message.mentions:
            data = self.afk.get(target.id)
            if not data:
                continue

            # rate-limit reminders per (author, target)
            key = (author.id, target.id)
            now = time.time()
            if now - self._recent_notices.get(key, 0.0) < self.MENTION_COOLDOWN_S:
                continue
            self._recent_notices[key] = now

            reason = data.get("reason") or "No reason provided."
            since_iso = data.get("since")
            try:
                dt = discord.utils.parse_time(since_iso)
                rel = discord.utils.format_dt(dt, style="R") if dt else "some time ago"
            except Exception:
                rel = "some time ago"

            to_notify.append(f"🛌 **{target.display_name}** is AFK (since {rel}): **{reason}**")

        if to_notify:
            try:
                await channel.send("\n".join(to_notify))
            except discord.Forbidden:
                pass

async def setup(bot: commands.Bot):
    await bot.add_cog(AFK(bot))