# cogs/purge.py
import discord
from discord import app_commands
from discord.ext import commands

# Notes:
# - Requires Manage Messages permission for both the invoker and the bot.
# - Discord only bulk-deletes messages younger than 14 days.
# - Keep intents.message_content = True in main.py for best results.

class Purge(commands.Cog):
    """Moderation: clear chat with simple, reliable commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # 1) Basic: delete the last N messages (anyone, any content)
    @commands.hybrid_command(name="purge", description="Delete the last N messages.")
    @app_commands.describe(amount="How many recent messages to delete (1–1000)")
    @commands.guild_only()
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True, read_message_history=True)
    async def purge(self, ctx: commands.Context, amount: int):
        amount = max(1, min(amount, 1000))
        deleted = await ctx.channel.purge(limit=amount, bulk=True, reason=f"Requested by {ctx.author}")
        await self._ack(ctx, f"🧹 Deleted **{len(deleted)}** message(s).")

    # 2) Only from a specific user
    @commands.hybrid_command(name="purgefrom", description="Delete messages from a specific user.")
    @app_commands.describe(amount="How many recent messages to scan (1–1000)",
                           user="Only delete messages from this user")
    @commands.guild_only()
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True, read_message_history=True)
    async def purgefrom(self, ctx: commands.Context, amount: int, user: discord.Member):
        amount = max(1, min(amount, 1000))
        def check(m: discord.Message) -> bool:
            return m.author.id == user.id
        deleted = await ctx.channel.purge(limit=amount, check=check, bulk=True, reason=f"Requested by {ctx.author}")
        await self._ack(ctx, f"🧹 Deleted **{len(deleted)}** message(s) from **{user}**.")

    # 3) Only messages containing some text (case-insensitive)
    @commands.hybrid_command(name="purgecontains", description="Delete messages containing text.")
    @app_commands.describe(amount="How many recent messages to scan (1–1000)",
                           text="Case-insensitive text to match")
    @commands.guild_only()
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True, read_message_history=True)
    async def purgecontains(self, ctx: commands.Context, amount: int, *, text: str):
        amount = max(1, min(amount, 1000))
        lower = text.lower()
        def check(m: discord.Message) -> bool:
            return bool(m.content) and lower in m.content.lower()
        deleted = await ctx.channel.purge(limit=amount, check=check, bulk=True, reason=f"Requested by {ctx.author}")
        await self._ack(ctx, f"🧹 Deleted **{len(deleted)}** message(s) containing “{text}”.")
    
    # 4) Only bot messages (handy for clearing test spam)
    @commands.hybrid_command(name="purgebots", description="Delete bot messages.")
    @app_commands.describe(amount="How many recent messages to scan (1–1000)")
    @commands.guild_only()
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True, read_message_history=True)
    async def purgebots(self, ctx: commands.Context, amount: int):
        amount = max(1, min(amount, 1000))
        def check(m: discord.Message) -> bool:
            return m.author.bot
        deleted = await ctx.channel.purge(limit=amount, check=check, bulk=True, reason=f"Requested by {ctx.author}")
        await self._ack(ctx, f"🤖 Deleted **{len(deleted)}** bot message(s).")

    async def _ack(self, ctx: commands.Context, message: str):
        # Ephemeral for slash; auto-clean for prefix where possible
        if getattr(ctx, "interaction", None):
            if not ctx.interaction.response.is_done():
                await ctx.interaction.response.send_message(message, ephemeral=True)
            else:
                await ctx.interaction.followup.send(message, ephemeral=True)
        else:
            try:
                msg = await ctx.reply(message, mention_author=False)
                await msg.delete(delay=5)
            except discord.Forbidden:
                pass

async def setup(bot: commands.Bot):
    await bot.add_cog(Purge(bot))