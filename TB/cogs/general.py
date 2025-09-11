import time
import discord
from discord import app_commands
from discord.ext import commands

class General(commands.Cog):
    """General fun & utility commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # Prefix command: !hello
    @commands.command(name="test")
    async def hello(self, ctx: commands.Context):
        await ctx.send(f"test, {ctx.author.mention}! Return")

    # Hybrid command: works as both !ping and /ping
    @commands.hybrid_command(name="ping", description="Check bot latency.")
    async def ping(self, ctx: commands.Context):
        start = time.perf_counter()
        msg = await ctx.reply("Pinging...")
        end = time.perf_counter()
        ws = round(self.bot.latency * 1000)
        rt = round((end - start) * 1000)
        await msg.edit(content=f"WebSocket: **{ws}ms**, Round-trip: **{rt}ms**")

    # Pure slash command: /userinfo
    @app_commands.command(name="userinfo", description="Show info about a user.")
    async def userinfo(self, interaction: discord.Interaction, member: discord.Member | None = None):
        member = member or interaction.user
        embed = discord.Embed(title=f"{member} • User info")
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="ID", value=str(member.id))
        embed.add_field(name="Joined", value=getattr(member, "joined_at", "N/A"))
        embed.add_field(name="Top Role", value=getattr(member.top_role, "name", "N/A"))
        await interaction.response.send_message(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(General(bot))