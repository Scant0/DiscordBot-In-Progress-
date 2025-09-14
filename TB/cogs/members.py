import discord
from discord.ext import commands
from discord import app_commands

class Members(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="memberstest", description="Show total and online member count")#change the 'memberstest' to name of your choice to initiate the command
    async def members(self, interaction: discord.Interaction):
        guild = interaction.guild
        total_members = guild.member_count
        online_members = sum(1 for m in guild.members if m.status == discord.Status.online)

        embed = discord.Embed(
            title=f"📊 Member Stats for {guild.name}",
            color=discord.Color.blue()
        )
        embed.add_field(name="Total Members", value=total_members, inline=True)
        embed.add_field(name="Online Members", value=online_members, inline=True)

        await interaction.response.send_message(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(Members(bot))
