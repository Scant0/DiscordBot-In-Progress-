# cogs/tickets.py
from __future__ import annotations
import asyncio
import io
import json
from pathlib import Path
from typing import Dict, Any, Optional

import discord
from discord.ext import commands
from discord import app_commands

DATA_DIR = Path("data")
STORE_FILE = DATA_DIR / "tickets.json"

PANEL_TITLE = "🎟️ Support Tickets"
PANEL_DESC = "Click below to open a ticket with the staff team."

# ---------- storage ----------
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

def _g(store: Dict[str, Any], gid: int) -> Dict[str, Any]:
    sgid = str(gid)
    store.setdefault("guilds", {})
    store["guilds"].setdefault(
        sgid,
        {
            "category_id": None,
            "staff_role_id": None,
            "transcript_channel_id": None,
            "embed_color": None,  # int (0xRRGGBB) or None
        },
    )
    return store["guilds"][sgid]

# ---------- helpers ----------
def _is_staff(member: discord.Member, staff_role_id: Optional[int]) -> bool:
    return bool(staff_role_id) and any(r.id == staff_role_id for r in member.roles)

def _extract_owner_id(channel: discord.TextChannel) -> Optional[int]:
    topic = channel.topic or ""
    key = "ticket_user="
    if key in topic:
        try:
            return int(topic.split(key, 1)[1].split()[0])
        except Exception:
            return None
    return None

def _with_owner_in_topic(topic: str | None, user_id: int) -> str:
    base = (topic or "").split(" ticket_user=", 1)[0].strip()
    return (base + f" ticket_user={user_id}").strip()

async def _build_transcript_bytes(channel: discord.TextChannel) -> bytes:
    lines = [f"# Transcript for #{channel.name} in {channel.guild.name}\n"]
    async for m in channel.history(limit=None, oldest_first=True):
        author = f"{m.author} ({m.author.id})"
        content = m.content or ""
        if m.attachments:
            atts = " ".join(a.url for a in m.attachments)
            content = (content + " " + atts).strip()
        lines.append(f"[{m.created_at:%Y-%m-%d %H:%M:%S}] {author}: {content}\n")
    return "\n".join(lines).encode("utf-8")

def _parse_hex_color(raw: str) -> Optional[int]:
    s = raw.strip().lstrip("#")
    if len(s) != 6:
        return None
    try:
        return int(s, 16)
    except ValueError:
        return None

def _color_for(guild: discord.Guild, store: Dict[str, Any]) -> discord.Color:
    cfg = _g(store, guild.id)
    val = cfg.get("embed_color")
    if isinstance(val, int):
        return discord.Color(val)
    return discord.Color.blurple()

# ---------- Views ----------
class TicketPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)  # persistent

    @discord.ui.button(label="Open Ticket", style=discord.ButtonStyle.blurple, custom_id="tt:open")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        if guild is None or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Use this in a server.", ephemeral=True)

        tickets: Tickets = interaction.client.get_cog("Tickets")  # type: ignore
        cfg = _g(tickets.store, guild.id)
        category_id = cfg.get("category_id")
        staff_role_id = cfg.get("staff_role_id")

        if not category_id or not staff_role_id:
            return await interaction.response.send_message(
                "Ticket system not configured. Ask an admin to run `/ticketpanel`.",
                ephemeral=True,
            )

        category = guild.get_channel(category_id)
        if not isinstance(category, discord.CategoryChannel):
            return await interaction.response.send_message("Configured category not found.", ephemeral=True)

        # Create channel
        base = f"ticket-{interaction.user.name}".replace(" ", "-").lower()
        name = base[:85]
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, read_message_history=True),
        }
        role = guild.get_role(staff_role_id)
        if role:
            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True, manage_channels=True
            )

        channel = await guild.create_text_channel(name, category=category, overwrites=overwrites)
        await channel.edit(topic=_with_owner_in_topic(channel.topic, interaction.user.id))

        await interaction.response.send_message(f"✅ Ticket created: {channel.mention}", ephemeral=True)
        await channel.send(f"{interaction.user.mention} thanks for opening a ticket! A staff member will be with you shortly.")

        col = _color_for(guild, tickets.store)
        close_embed = discord.Embed(
            title="Support team ticket controls",
            description="Press **Close** when you’re finished with this ticket.",
            color=col,
        )
        await channel.send(embed=close_embed, view=TicketCloseView())

class TicketCloseView(discord.ui.View):
    """Shown while ticket is open. Staff-only button to close/lock the ticket."""
    def __init__(self):
        super().__init__(timeout=None)

    async def _staff_check(self, interaction: discord.Interaction) -> Optional[int]:
        if not (interaction.guild and isinstance(interaction.user, discord.Member) and isinstance(interaction.channel, discord.TextChannel)):
            await interaction.response.send_message("Not available here.", ephemeral=True)
            return None
        tickets: Tickets = interaction.client.get_cog("Tickets")  # type: ignore
        cfg = _g(tickets.store, interaction.guild.id)
        staff_role_id = cfg.get("staff_role_id")
        if not _is_staff(interaction.user, staff_role_id):
            await interaction.response.send_message("Only staff can use this.", ephemeral=True)
            return None
        return staff_role_id

    @discord.ui.button(label="Close", emoji="🔒", style=discord.ButtonStyle.danger, custom_id="tt:close")
    async def close(self, interaction: discord.Interaction, _: discord.ui.Button):
        staff_role_id = await self._staff_check(interaction)
        if staff_role_id is None:
            return
        channel: discord.TextChannel = interaction.channel  # type: ignore
        guild = interaction.guild
        tickets: Tickets = interaction.client.get_cog("Tickets")  # type: ignore

        opener_id = _extract_owner_id(channel)
        opener = guild.get_member(opener_id) if (guild and opener_id) else None

        # Lock opener's send perms
        overwrites = channel.overwrites
        if opener:
            ow = overwrites.get(opener) or discord.PermissionOverwrite()
            ow.send_messages = False
            ow.view_channel = True
            overwrites[opener] = ow
            await channel.edit(overwrites=overwrites)

        col = _color_for(guild, tickets.store)
        embed = discord.Embed(
            title=f"Ticket Closed by {interaction.user.mention}",
            description="Support team ticket controls",
            color=col,
        )
        await interaction.response.edit_message(embed=embed, view=TicketControlsView())

class TicketControlsView(discord.ui.View):
    """Shown after close: staff-only Transcript / Open / Delete."""
    def __init__(self):
        super().__init__(timeout=None)

    async def _staff_check(self, interaction: discord.Interaction) -> Optional[Dict[str, Any]]:
        if not (interaction.guild and isinstance(interaction.user, discord.Member) and isinstance(interaction.channel, discord.TextChannel)):
            await interaction.response.send_message("Not available here.", ephemeral=True)
            return None
        tickets: Tickets = interaction.client.get_cog("Tickets")  # type: ignore
        cfg = _g(tickets.store, interaction.guild.id)
        staff_role_id = cfg.get("staff_role_id")
        if not _is_staff(interaction.user, staff_role_id):
            await interaction.response.send_message("Only staff can use this.", ephemeral=True)
            return None
        return cfg

    @discord.ui.button(label="Transcript", emoji="📄", style=discord.ButtonStyle.secondary, custom_id="tt:transcript")
    async def transcript(self, interaction: discord.Interaction, _: discord.ui.Button):
        cfg = await self._staff_check(interaction)
        if cfg is None:
            return
        tickets: Tickets = interaction.client.get_cog("Tickets")  # type: ignore
        channel: discord.TextChannel = interaction.channel  # type: ignore
        data = await _build_transcript_bytes(channel)
        file = discord.File(io.BytesIO(data), filename=f"{channel.name}-transcript.txt")

        trans_id = cfg.get("transcript_channel_id")
        target = interaction.guild.get_channel(trans_id) if trans_id else None
        if isinstance(target, discord.TextChannel):
            await target.send(file=file, content=f"Transcript for {channel.mention}")
            await interaction.response.send_message("✅ Transcript saved.", ephemeral=True)
        else:
            await interaction.response.send_message("No transcript channel configured; sending here.", ephemeral=True)
            await channel.send(file=file, content="Transcript")

    @discord.ui.button(label="Open", emoji="🔓", style=discord.ButtonStyle.success, custom_id="tt:reopen")
    async def reopen(self, interaction: discord.Interaction, _: discord.ui.Button):
        cfg = await self._staff_check(interaction)
        if cfg is None:
            return
        tickets: Tickets = interaction.client.get_cog("Tickets")  # type: ignore
        channel: discord.TextChannel = interaction.channel  # type: ignore

        opener_id = _extract_owner_id(channel)
        opener = interaction.guild.get_member(opener_id) if (interaction.guild and opener_id) else None

        overwrites = channel.overwrites
        if opener:
            ow = overwrites.get(opener) or discord.PermissionOverwrite()
            ow.send_messages = True
            ow.view_channel = True
            overwrites[opener] = ow
            await channel.edit(overwrites=overwrites)

        await interaction.response.send_message("🔓 Ticket reopened.", ephemeral=True)
        col = _color_for(interaction.guild, tickets.store)
        embed = discord.Embed(
            title="Support team ticket controls",
            description="Press **Close** when you’re finished with this ticket.",
            color=col,
        )
        await interaction.message.edit(embed=embed, view=TicketCloseView())

    @discord.ui.button(label="Delete", emoji="⛔", style=discord.ButtonStyle.danger, custom_id="tt:delete")
    async def delete(self, interaction: discord.Interaction, _: discord.ui.Button):
        cfg = await self._staff_check(interaction)
        if cfg is None:
            return
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            return await interaction.response.send_message("Not a text channel.", ephemeral=True)

        # Disable buttons to prevent double-click spam
        for child in self.children:
            child.disabled = True
        try:
            await interaction.response.send_message("🗑️ Ticket will be deleted in a few seconds", ephemeral=False)
            await interaction.message.edit(view=self)
        except Exception:
            pass

        try:
            await asyncio.sleep(5)
            await channel.delete(reason=f"Ticket deleted by {interaction.user}")
        except discord.Forbidden:
            await interaction.followup.send("I don't have permission to delete this channel.", ephemeral=True)

# ---------- Cog ----------
class Tickets(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.store = _load_store()

    async def cog_load(self):
        # persistent views on startup
        self.bot.add_view(TicketPanelView())
        self.bot.add_view(TicketCloseView())
        self.bot.add_view(TicketControlsView())

    async def _show_config(self, guild: discord.Guild) -> str:
        cfg = _g(self.store, guild.id)
        parts = []
        cat = guild.get_channel(cfg.get("category_id") or 0)
        parts.append(f"Category: {cat.mention if isinstance(cat, discord.CategoryChannel) else '`not set`'}")
        role = guild.get_role(cfg.get("staff_role_id") or 0)
        parts.append(f"Staff role: {role.mention if role else '`not set`'}")
        ch = guild.get_channel(cfg.get("transcript_channel_id") or 0)
        parts.append(f"Transcript channel: {ch.mention if isinstance(ch, discord.TextChannel) else '`not set`'}")
        col = cfg.get("embed_color")
        parts.append(f"Embed color: {'#' + format(col, '06X') if isinstance(col, int) else '`default (blurple)`'}")
        return "\n".join(parts)

    @commands.hybrid_command(name="ticketpanel", description="Post the ticket panel and configure it.")
    @app_commands.describe(
        category="Category where tickets will be created",
        staff_role="Role that can manage tickets",
        transcript_channel="Channel where transcripts will be saved",
        embed_hex="Optional hex color for embeds (e.g., #00AAFF or 00AAFF)",
    )
    @app_commands.default_permissions(manage_guild=True)
    @commands.has_permissions(manage_guild=True)
    async def ticketpanel(
        self,
        ctx: commands.Context,
        category: discord.CategoryChannel,
        staff_role: discord.Role,
        transcript_channel: discord.TextChannel,
        embed_hex: Optional[str] = None,
    ):
        if ctx.guild is None:
            return
        cfg = _g(self.store, ctx.guild.id)
        cfg["category_id"] = category.id
        cfg["staff_role_id"] = staff_role.id
        cfg["transcript_channel_id"] = transcript_channel.id

        # Optional color set here only (no separate command)
        color_val = None
        if embed_hex:
            color_val = _parse_hex_color(embed_hex)
            if color_val is None:
                if ctx.interaction:
                    await ctx.interaction.response.send_message("⚠️ Invalid hex; using default color.", ephemeral=True)
                else:
                    await ctx.send("⚠️ Invalid hex; using default color.", delete_after=6)
        cfg["embed_color"] = color_val
        _save_store(self.store)

        color = _color_for(ctx.guild, self.store)
        embed = discord.Embed(title=PANEL_TITLE, description=PANEL_DESC, color=color)
        await ctx.channel.send(embed=embed, view=TicketPanelView())

        # No visible bot reply to the command:
        if ctx.interaction:
            if not ctx.interaction.response.is_done():
                await ctx.interaction.response.send_message("✅ Panel posted.", ephemeral=True)
            else:
                await ctx.interaction.followup.send("✅ Panel posted.", ephemeral=True)
        else:
            try:
                await ctx.message.delete()
            except Exception:
                pass

    @commands.hybrid_command(name="ticketconfig", description="Show ticket system configuration.")
    @app_commands.default_permissions(manage_guild=True)
    @commands.has_permissions(manage_guild=True)
    async def ticketconfig(self, ctx: commands.Context):
        if ctx.guild is None:
            return
        info = await self._show_config(ctx.guild)
        if ctx.interaction:
            await ctx.interaction.response.send_message(info, ephemeral=True)
        else:
            await ctx.send(info, delete_after=10)

async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))