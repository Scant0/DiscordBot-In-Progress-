import discord
from discord.ext import commands
from datetime import datetime

class Logger(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        # Channels for logs
        self.edit_logs_channel_id = 1414955646477930527
        self.delete_logs_channel_id = 1414955646477930527
        self.member_update_channel_id = 1400540866816245992
        self.server_update_channel_id = 1400540866816245992

        # Embed colors
        self.edit_color = discord.Color(int("d30000", 16))
        self.delete_color = discord.Color(int("d30000", 16))
        self.member_update_color = discord.Color(int("d30000", 16))
        self.server_update_color = discord.Color(int("d30000", 16))

    # ------------------- MESSAGE EDIT -------------------
    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if before.author.bot or before.content == after.content:
            return
        logs_channel = self.bot.get_channel(self.edit_logs_channel_id)
        if not logs_channel:
            return

        embed = discord.Embed(
            title="📝 Message Edited",
            color=self.edit_color,
            timestamp=datetime.utcnow()
        )
        embed.set_author(name=str(before.author), icon_url=before.author.display_avatar.url)
        embed.add_field(name="Before", value=before.content or "*No content*", inline=False)
        embed.add_field(name="After", value=after.content or "*No content*", inline=False)
        embed.add_field(name="Channel", value=before.channel.mention, inline=True)
        embed.add_field(name="Message Link", value=f"[Jump]({after.jump_url})", inline=True)
        embed.set_footer(text=f"User ID: {before.author.id}")

        await logs_channel.send(embed=embed)

    # ------------------- MESSAGE DELETE -------------------
    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.author.bot:
            return
        logs_channel = self.bot.get_channel(self.delete_logs_channel_id)
        if not logs_channel:
            return

        embed = discord.Embed(
            title="🗑 Message Deleted",
            color=self.delete_color,
            timestamp=datetime.utcnow()
        )
        embed.set_author(name=str(message.author), icon_url=message.author.display_avatar.url)
        embed.add_field(name="Content", value=message.content or "*No content*", inline=False)
        embed.add_field(name="Channel", value=message.channel.mention, inline=True)
        embed.set_footer(text=f"User ID: {message.author.id}")

        await logs_channel.send(embed=embed)

    # ------------------- MEMBER UPDATE -------------------
    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        logs_channel = self.bot.get_channel(self.member_update_channel_id)
        if not logs_channel:
            return

        changes = []
        embed = discord.Embed(
            title="👤 Member Updated",
            color=self.member_update_color,
            timestamp=datetime.utcnow()
        )

        if before.name != after.name:
            changes.append(f"**Username:** {before.name} → {after.name}")
        if before.nick != after.nick:
            changes.append(f"**Nickname:** {before.nick or '*None*'} → {after.nick or '*None*'}")
        if before.avatar != after.avatar:
            embed.set_thumbnail(url=after.avatar.url if after.avatar else None)
            changes.append("**Avatar Changed**")

        # Roles
        before_roles = set(before.roles)
        after_roles = set(after.roles)
        added_roles = after_roles - before_roles
        removed_roles = before_roles - after_roles

        if added_roles:
            changes.append("**Roles Added:** " + ", ".join([r.mention for r in added_roles]))
        if removed_roles:
            changes.append("**Roles Removed:** " + ", ".join([r.mention for r in removed_roles]))

        if changes:
            embed.add_field(name=f"{after}", value="\n".join(changes), inline=False)
            embed.set_footer(text=f"User ID: {after.id}")
            await logs_channel.send(embed=embed)

    # ------------------- GUILD CHANNEL UPDATE -------------------
    @commands.Cog.listener()
    async def on_guild_channel_update(self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel):
        logs_channel = self.bot.get_channel(self.server_update_channel_id)
        if not logs_channel:
            return

        changes = []
        if before.name != after.name:
            changes.append(f"Channel Update {before.name} → {after.name}")
        if before.permissions_synced != after.permissions_synced or before.overwrites != after.overwrites:
            changes.append("**Permissions Changed**")
        if before.type != after.type:
            changes.append(f"**Channel Type Changed:** {before.type} → {after.type}")

        if changes:
            embed = discord.Embed(
                title=f"⚙️ Channel Updated:",
                color=self.server_update_color,
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="Changes", value="\n".join(changes), inline=False)
            embed.set_footer(text=f"Channel ID: {after.id}")
            await logs_channel.send(embed=embed)

    # ------------------- ROLE UPDATE -------------------
    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role):
        logs_channel = self.bot.get_channel(self.server_update_channel_id)
        if not logs_channel:
            return

        changes = []
        if before.name != after.name:
            changes.append(f"**Name:** {before.name} → {after.name}")
        if before.color != after.color:
            changes.append(f"**Color:** {before.color} → {after.color}")
        if before.permissions != after.permissions:
            changes.append("**Permissions Changed**")

        if changes:
            embed = discord.Embed(
                title=f"🎨 Role Updated: {after.name}",
                color=after.color if after.color.value != 0 else discord.Color.red(),
                timestamp=datetime.utcnow()
            )
            embed.set_author(name=f"{after.name}", icon_url=str(after.guild.icon.url) if after.guild.icon else None)
            embed.add_field(name="Changes", value="\n".join(changes), inline=False)
            embed.set_footer(text=f"Role ID: {after.id}")
            await logs_channel.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Logger(bot))
