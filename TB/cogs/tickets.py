# cogs/tickets.py
from __future__ import annotations
import io
import textwrap
from typing import Optional, Iterable

import discord
from discord import app_commands
from discord.ext import commands

# ================== CONFIG (EDIT THESE) ==================
TICKET_CATEGORY_ID = 1415810015876612169  # The category where ticket channels should be created
STAFF_ROLE_IDS: set[int] = {1415420040366526656}  # Roles that can view all tickets
TRANSCRIPT_LOG_CHANNEL_ID = 1415809905541255339   # Where transcripts get posted (optional; set 0 to disable)
PANEL_TITLE = "Support Tickets"
PANEL_DESC = "Need help? Click the button to open a private ticket with staff."
TICKET_CHANNEL_PREFIX = "ticket"
# =========================================================

# Utility: find a category safely
def get_category(guild: discord.Guild, cat_id: int) -> Optional[discord.CategoryChannel]:
    return guild.get_channel(cat_id) if cat_id else None

def _staff_overwrites(guild: discord.Guild) -> Iterable[tuple[discord.Role, discord.PermissionOverwrite]]:
    for rid in STAFF_ROLE_IDS:
        role = guild.get_role(rid)
        if role:
            yield role, discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

class TicketView(discord.ui.View):
    """Persistent panel with an 'Open Ticket' button."""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Open Ticket", style=discord.ButtonStyle.primary, custom_id="ticket:open")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.guild is None:
            return await interaction.response.send_message("Use this in a server.", ephemeral=True)

        guild = interaction.guild

        # Check category exists
        category = get_category(guild, TICKET_CATEGORY_ID)
        if category is None:
            return await interaction.response.send_message(
                "Ticket system is not configured (category missing).", ephemeral=True
            )

        # Prevent multiple open tickets (search channels by topic containing user id)
        for ch in category.text_channels:
            if ch.topic and f"uid:{interaction.user.id}" in ch.topic:
                url = ch.mention
                return await interaction.response.send_message(
                    f"You already have an open ticket: {url}", ephemeral=True
                )

        # Build permission overwrites
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True, attach_files=True, embed_links=True
            ),
        }
        for role, ow in _staff_overwrites(guild):
            overwrites[role] = ow

        # Create channel name
        counter = sum(1 for _ in category.text_channels) + 1
        name = f"{TICKET_CHANNEL_PREFIX}-{counter:04d}"

        # Create channel
        topic = f"Support ticket • uid:{interaction.user.id}"
        try:
            channel = await guild.create_text_channel(
                name=name,
                category=category,
                overwrites=overwrites,
                topic=topic,
                reason=f"Ticket opened by {interaction.user} ({interaction.user.id})"
            )
        except discord.Forbidden:
            return await interaction.response.send_message("I lack permission to create channels.", ephemeral=True)
        except discord.HTTPException:
            return await interaction.response.send_message("Failed to create the ticket channel.", ephemeral=True)

        # Acknowledge + send welcome
        await interaction.response.send_message(f"✅ Created {channel.mention}", ephemeral=True)

        # Post the ticket header with a close button
        header = discord.Embed(
            title="🎫 New Ticket",
            description=(
                f"Hello {interaction.user.mention}! A staff member will be with you shortly.\n"
                f"Use the button below to **close** this ticket when resolved."
            ),
            color=discord.Color.blurple(),
        )
        await channel.send(content=self._staff_ping(guild), embed=header, view=TicketCloseView(opener_id=interaction.user.id))

    @staticmethod
    def _staff_ping(guild: discord.Guild) -> str:
        mentions = []
        for rid in STAFF_ROLE_IDS:
            role = guild.get_role(rid)
            if role:
                mentions.append(role.mention)
        return " ".join(mentions) if mentions else ""

class TicketCloseView(discord.ui.View):
    """Close button shown inside each ticket."""
    def __init__(self, opener_id: int):
        super().__init__(timeout=None)
        self.opener_id = opener_id

    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.danger, custom_id="ticket:close")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel) or interaction.guild is None:
            return await interaction.response.send_message("This can only be used in a ticket channel.", ephemeral=True)

        # Only staff or the ticket opener can close
        is_staff = any(isinstance(m, discord.Member) and any(r.id in STAFF_ROLE_IDS for r in m.roles)
                       for m in [interaction.user])
        is_opener = f"uid:{interaction.user.id}" in (channel.topic or "")
        if not (is_staff or is_opener):
            return await interaction.response.send_message("Only staff or the ticket opener can close this ticket.", ephemeral=True)

        await interaction.response.defer(ephemeral=True, thinking=True)

        # Lock channel: remove send perms for everyone except staff
        overwrites = channel.overwrites
        for target in list(overwrites.keys()):
            if isinstance(target, discord.Member) or target == interaction.guild.default_role:
                ow = overwrites[target]
                ow.send_messages = False
                overwrites[target] = ow
        for rid in STAFF_ROLE_IDS:
            role = interaction.guild.get_role(rid)
            if role and role in overwrites:
                ow = overwrites[role]
                ow.send_messages = True
                overwrites[role] = ow
        try:
            await channel.edit(overwrites=overwrites, reason=f"Ticket closed by {interaction.user}")
        except discord.HTTPException:
            pass

        # Build transcript (text)
        transcript_bytes = await build_transcript_bytes(channel)

        # Post transcript to log channel (optional)
        if TRANSCRIPT_LOG_CHANNEL_ID:
            log_ch = interaction.guild.get_channel(TRANSCRIPT_LOG_CHANNEL_ID)
            if isinstance(log_ch, discord.TextChannel):
                try:
                    await log_ch.send(
                        content=f"📄 Transcript for {channel.mention} (closed by {interaction.user.mention})",
                        file=discord.File(io.BytesIO(transcript_bytes), filename=f"{channel.name}.txt"),
                    )
                except discord.HTTPException:
                    pass

        # Send transcript in the ticket channel too, then delete
        try:
            await channel.send(
                content="This ticket will be deleted shortly. Transcript attached.",
                file=discord.File(io.BytesIO(transcript_bytes), filename=f"{channel.name}.txt"),
                view=None
            )
        except discord.HTTPException:
            pass

        try:
            await channel.delete(reason=f"Ticket closed by {interaction.user}")
        except discord.HTTPException:
            # If delete fails, at least remove the close button so it’s not spammed
            try:
                await interaction.followup.send("Tried to delete channel but failed. You can remove it manually.", ephemeral=True)
            except Exception:
                pass

async def build_transcript_bytes(channel: discord.TextChannel) -> bytes:
    """Fetch channel history newest→oldest and format as text."""
    lines: list[str] = []
    lines.append(f"Transcript for #{channel.name} (id: {channel.id}) in {channel.guild} • {channel.jump_url}")
    lines.append("-" * 72)

    async for msg in channel.history(limit=None, oldest_first=True):
        author = f"{msg.author} ({msg.author.id})"
        ts = msg.created_at.strftime("%Y-%m-%d %H:%M:%S")
        content = msg.content or ""
        # Include attachments URLs
        if msg.attachments:
            atts = " ".join(att.url for att in msg.attachments)
            content = (content + " " + atts).strip()
        # Include embeds short summary
        if msg.embeds:
            content = (content + " [embeds]").strip()
        # Keep lines neat
        for chunk in textwrap.wrap(content, width=120) or [""]:
            lines.append(f"[{ts}] {author}: {chunk}")

    text = "\n".join(lines) + "\n"
    return text.encode("utf-8", errors="replace")

class Tickets(commands.Cog):
    """Ticket system: panel + per-user private ticket channels."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # Re-add the persistent view on startup
    @commands.Cog.listener()
    async def on_ready(self):
        try:
            self.bot.add_view(TicketView())  # persistent by custom_id
        except Exception:
            pass

    # Post the panel
    @commands.hybrid_command(name="ticketpanel", description="Post the ticket panel with the Open Ticket button.")
    @app_commands.default_permissions(manage_guild=True)
    @commands.has_permissions(manage_guild=True)
    async def ticketpanel(self, ctx: commands.Context):
        if ctx.guild is None:
            return await ctx.reply("Run this in a server.", mention_author=False)
        embed = discord.Embed(title=PANEL_TITLE, description=PANEL_DESC, color=discord.Color.blurple())
        await ctx.reply(embed=embed, view=TicketView(), mention_author=False)

async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))