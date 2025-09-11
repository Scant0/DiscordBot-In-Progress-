# cogs/avatar.py
from __future__ import annotations
import discord
from discord.ext import commands

# === SET YOUR LOCKED HEX COLOUR HERE (0xRRGGBB) ===
AVATAR_EMBED_HEX = 0x42a832  # Discord blurple by default (example: 0xFF0000 for red)

class Avatar(commands.Cog):
    """Show a user's enlarged avatar (4096px) with a locked embed colour."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(name="avatar", description="Show an enlarged avatar (4096px).")
    async def avatar(self, ctx: commands.Context, user: discord.Member | None = None):
        # default to the invoker (server member)
        member = user or (ctx.author if isinstance(ctx.author, discord.Member) else None)
        if member is None:
            await self._reply(ctx, "I couldn't find that member.", ephemeral=True)
            return

        # prefer server-specific avatar if set; otherwise global
        asset: discord.Asset = member.guild_avatar or member.display_avatar

        # max size (keep dynamic for GIFs)
        try:
            asset = asset.with_size(4096)
        except AttributeError:
            asset = asset.replace(size=4096)

        embed = discord.Embed(
            title=f"{member.display_name}'s Avatar",
            color=discord.Color(AVATAR_EMBED_HEX),
        )
        embed.set_image(url=asset.url)

        # Always non-ephemeral so it appears like a normal image post
        await self._reply(ctx, embed=embed, ephemeral=False)

    # helper for hybrid replies
    async def _reply(
        self,
        ctx: commands.Context,
        content: str | None = None,
        *,
        embed: discord.Embed | None = None,
        ephemeral: bool = False,
    ):
        if getattr(ctx, "interaction", None):
            if not ctx.interaction.response.is_done():
                await ctx.interaction.response.send_message(content=content, embed=embed, ephemeral=ephemeral)
            else:
                await ctx.interaction.followup.send(content=content, embed=embed, ephemeral=ephemeral)
        else:
            await ctx.reply(content=content, embed=embed, mention_author=False)

async def setup(bot: commands.Bot):
    await bot.add_cog(Avatar(bot))