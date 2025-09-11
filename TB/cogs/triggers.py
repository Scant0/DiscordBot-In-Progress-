# cogs/triggers.py
from __future__ import annotations
import time
import discord
from discord.ext import commands

class Triggers(commands.Cog):
    """
    Non-regex keyword -> response auto-replies.
    - Single-word keys match as WHOLE WORDS.
    - Multi-word keys match as simple substrings.
    - We do NOT call process_commands; instead we detect real commands and skip.
    """

    # === Edit your triggers here ===
    TRIGGERS: dict[str, str] = {
        "1": "2",     # single word -> whole-word match
        "Testing": "Tested",         # single word -> whole-word match
        # "hello there": "General Kenobi.",  # phrase -> substring match
        # "good morning": "Good morning! ☀️",
    }
    COOLDOWN_SECONDS = 3  # set to 0 to disable
    # ===============================

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Normalize keys and pre-split into single-word vs phrase triggers
        norm = {k.strip().lower(): v for k, v in self.TRIGGERS.items() if k.strip()}
        self.single_word_triggers: dict[str, str] = {k: v for k, v in norm.items() if " " not in k}
        self.phrase_triggers: dict[str, str] = {k: v for k, v in norm.items() if " " in k}
        self._cooldowns: dict[tuple[int, str], float] = {}

    @commands.Cog.listener()
    async def on_ready(self):
        print(
            f"[triggers] loaded with {len(self.single_word_triggers)+len(self.phrase_triggers)} trigger(s). "
            f"words={list(self.single_word_triggers.keys())}, phrases={list(self.phrase_triggers.keys())}"
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Ignore bots/DMs
        if message.author.bot or message.guild is None:
            return

        # If this is a valid command (e.g., !ping or a slash), skip triggers
        ctx = await self.bot.get_context(message)
        if ctx and ctx.valid:
            return

        text = (message.content or "").lower()
        if not text:
            return

        # Build a basic word set WITHOUT regex:
        # Replace non-alphanumeric with spaces, then split.
        # This gives us simple whole-word matching for single-word triggers.
        clean_chars = []
        for ch in text:
            clean_chars.append(ch if ch.isalnum() else " ")
        word_set = set("".join(clean_chars).split())

        # 1) Try single-word triggers (whole-word)
        hit_key = None
        reply = None
        for key, rep in self.single_word_triggers.items():
            if key in word_set:
                hit_key, reply = key, rep
                break

        # 2) If none, try phrase triggers (substring)
        if reply is None:
            for key, rep in self.phrase_triggers.items():
                if key in text:
                    hit_key, reply = key, rep
                    break

        if reply is None:
            return

        # Per-channel+trigger cooldown
        if self.COOLDOWN_SECONDS > 0:
            now = time.time()
            cd_key = (message.channel.id, hit_key)
            last = self._cooldowns.get(cd_key, 0.0)
            if now - last < self.COOLDOWN_SECONDS:
                return
            self._cooldowns[cd_key] = now

        try:
            await message.channel.send(reply)
        except discord.Forbidden:
            pass  # no send permission; ignore

async def setup(bot: commands.Bot):
    await bot.add_cog(Triggers(bot))