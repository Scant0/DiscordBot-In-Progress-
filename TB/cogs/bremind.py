# cogs/bremind.py
from __future__ import annotations
import json
import time
import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any

import discord
from discord.ext import commands, tasks
from discord import app_commands

# --- Constants ---
DISBOARD_BOT_ID = 302050872383242240  # official DISBOARD bot
DATA_DIR = Path("data")
STORE_FILE = DATA_DIR / "bremind.json"

# Fixed 2h cooldown (no command to change)
DEFAULT_COOLDOWN = 2 * 60 * 60  # seconds

DEFAULT_EMBED = {
    "title": "🔔 It's time to bump!",
    "description": "Please do /bump to bump the server again.",
    "color": 0x5865F2,
    "thumbnail": None,
    "footer": "",
}

# Auto-rename is always ON if channel_id is set.
DEFAULT_RENAME = {
    "channel_id": None,                          # channel to rename
    "ready_name": "bump-ready",
    "cooldown_name": "bump-wait-{minutes}m",     # {minutes} -> remaining minutes (ceil)
}

DEFAULT_BUMP_REPLY = "Thanks {user} for bumping! Next bump in {minutes} minutes."

# ---------------- Persistence helpers ----------------
def _ensure_store() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    if not STORE_FILE.exists():
        STORE_FILE.write_text(json.dumps({}, indent=2), encoding="utf-8")

def _load_all() -> Dict[str, Any]:
    _ensure_store()
    try:
        return json.loads(STORE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _save_all(data: Dict[str, Any]) -> None:
    try:
        STORE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass

# ---------------- Data model ----------------
@dataclass
class GuildState:
    enabled: bool = True  # always enabled
    bump_channel_id: Optional[int] = None     # where reminders are sent
    ping_role_id: Optional[int] = None        # role to mention on reminder
    cooldown_s: int = DEFAULT_COOLDOWN

    last_bump_ts: Optional[int] = None
    reminder_sent_for_ts: Optional[int] = None

    embed: Dict[str, Any] = None
    rename: Dict[str, Any] = None
    bump_reply_template: Optional[str] = DEFAULT_BUMP_REPLY  # None => disabled

    def __post_init__(self):
        if self.embed is None:
            self.embed = dict(DEFAULT_EMBED)
        if self.rename is None:
            self.rename = dict(DEFAULT_RENAME)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "GuildState":
        gs = cls()
        gs.enabled = bool(d.get("enabled", True))
        gs.bump_channel_id = d.get("bump_channel_id")
        gs.ping_role_id = d.get("ping_role_id")
        gs.cooldown_s = int(d.get("cooldown_s", DEFAULT_COOLDOWN))
        gs.last_bump_ts = d.get("last_bump_ts")
        gs.reminder_sent_for_ts = d.get("reminder_sent_for_ts")
        gs.embed = d.get("embed", dict(DEFAULT_EMBED))
        gs.rename = d.get("rename", dict(DEFAULT_RENAME))
        gs.bump_reply_template = d.get("bump_reply_template", DEFAULT_BUMP_REPLY)
        for k, v in DEFAULT_RENAME.items():
            gs.rename.setdefault(k, v)
        for k, v in DEFAULT_EMBED.items():
            gs.embed.setdefault(k, v)
        return gs

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "bump_channel_id": self.bump_channel_id,
            "ping_role_id": self.ping_role_id,
            "cooldown_s": self.cooldown_s,
            "last_bump_ts": self.last_bump_ts,
            "reminder_sent_for_ts": self.reminder_sent_for_ts,
            "embed": self.embed,
            "rename": self.rename,
            "bump_reply_template": self.bump_reply_template,
        }

# ---------------- UI: Modal + Dropdown for Embed Editing ----------------
class EmbedFieldModal(discord.ui.Modal, title="Edit Embed"):
    def __init__(self, field: str, current: Optional[str] = None):
        super().__init__(timeout=180)
        self.field = field

        label_map = {
            "title": "Title (<=256 chars)",
            "description": "Description (<=4000 chars)",
            "color": "Color hex (#5865F2 or 0x5865F2)",
            "thumbnail": "Thumbnail URL",
            "footer": "Footer (<=2000 chars)",
        }
        style_map = {"description": discord.TextStyle.paragraph}
        default = current or ""
        # IMPORTANT: TextInput must be <= 4000 per Discord API
        self.input = discord.ui.TextInput(
            label=label_map.get(field, field),
            default=default,
            required=False,
            style=style_map.get(field, discord.TextStyle.short),
            max_length=4000 if field == "description" else 1024,
        )
        self.add_item(self.input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        self.value = str(self.input.value or "").strip()

class EmbedEditorView(discord.ui.View):
    def __init__(self, cog: "Bremind", guild_id: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id

        options = [
            discord.SelectOption(label="Title", value="title", description="Edit the embed title"),
            discord.SelectOption(label="Description", value="description", description="Edit the description"),
            discord.SelectOption(label="Color", value="color", description="Set color in hex"),
            discord.SelectOption(label="Thumbnail URL", value="thumbnail", description="Set thumbnail image URL"),
            discord.SelectOption(label="Footer", value="footer", description="Edit footer text"),
            discord.SelectOption(label="Preview", value="preview", description="Show the current embed"),
            discord.SelectOption(label="Reset to defaults", value="reset", description="Restore default embed"),
        ]
        select = discord.ui.Select(
            placeholder="Choose what to edit…",
            min_values=1,
            max_values=1,
            options=options,
        )
        select.callback = self.on_select
        self.add_item(select)

    async def on_select(self, interaction: discord.Interaction):
        st = self.cog._state(self.guild_id)
        choice = interaction.data.get("values", [""])[0]  # type: ignore

        async def _save_and_ack(msg: str):
            self.cog._persist_all()
            await interaction.followup.send(msg, ephemeral=True)

        if choice == "preview":
            await interaction.response.defer(ephemeral=True)
            await interaction.followup.send(embed=self.cog._build_embed(st), ephemeral=True)
            return

        if choice == "reset":
            await interaction.response.defer(ephemeral=True)
            st.embed = dict(DEFAULT_EMBED)
            self.cog._persist_all()
            await interaction.followup.send("✅ Embed reset to defaults.", ephemeral=True)
            return

        # For editable fields, open modal
        current_value = None
        if choice in ("title", "description", "thumbnail", "footer"):
            current_value = str(st.embed.get(choice) or "")
        elif choice == "color":
            current_value = hex(int(st.embed.get("color") or DEFAULT_EMBED["color"]))

        modal = EmbedFieldModal(choice, current=current_value)
        await interaction.response.send_modal(modal)

        try:
            _ = await modal.wait()
        except Exception:
            return
        if getattr(modal, "value", None) is None:
            return

        if choice == "title":
            st.embed["title"] = modal.value[:256] if modal.value else None
            return await _save_and_ack("✅ Title updated.")
        if choice == "description":
            st.embed["description"] = modal.value[:4000] if modal.value else None
            return await _save_and_ack("✅ Description updated.")
        if choice == "thumbnail":
            st.embed["thumbnail"] = modal.value or None
            return await _save_and_ack("✅ Thumbnail updated.")
        if choice == "footer":
            st.embed["footer"] = modal.value[:2000] if modal.value else None
            return await _save_and_ack("✅ Footer updated.")
        if choice == "color":
            val = modal.value
            if val:
                s = val.strip().lower()
                if s.startswith("#"):
                    s = "0x" + s[1:]
                try:
                    st.embed["color"] = int(s, 16)
                except ValueError:
                    return await interaction.followup.send(
                        "❌ Invalid color. Use hex like `#5865F2`.", ephemeral=True
                    )
            else:
                st.embed["color"] = DEFAULT_EMBED["color"]
            return await _save_and_ack("✅ Color updated.")

# ---------------- Cog ----------------
class Bremind(commands.Cog):
    """DISBOARD bump reminder + channel rename helper (auto-rename is always active if a rename channel is set)."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._data: Dict[str, Any] = _load_all()
        self._states: Dict[int, GuildState] = {}

        for gid_str, payload in self._data.items():
            try:
                gid = int(gid_str)
                self._states[gid] = GuildState.from_dict(payload)
            except Exception:
                continue

        self._tick.start()

    def cog_unload(self):
        if self._tick.is_running():
            self._tick.cancel()
        self._persist_all()

    # ---------- util / perms ----------
    async def _can_manage(self, ctx: commands.Context) -> bool:
        if await self.bot.is_owner(ctx.author):
            return True
        if isinstance(ctx.author, discord.Member):
            perms = ctx.channel.permissions_for(ctx.author)
            return perms.manage_guild
        return False

    def _state(self, guild_id: int) -> GuildState:
        st = self._states.get(guild_id)
        if not st:
            st = GuildState()
            self._states[guild_id] = st
            self._persist_all()
        return st

    def _persist_all(self) -> None:
        out = {str(gid): st.to_dict() for gid, st in self._states.items()}
        _save_all(out)

    def _build_embed(self, st: GuildState) -> discord.Embed:
        title = st.embed.get("title") or DEFAULT_EMBED["title"]
        desc = st.embed.get("description") or DEFAULT_EMBED["description"]
        color = int(st.embed.get("color") or DEFAULT_EMBED["color"])
        emb = discord.Embed(title=title, description=desc, color=color)
        thumb = st.embed.get("thumbnail")
        if thumb:
            emb.set_thumbnail(url=thumb)
        footer = st.embed.get("footer")
        if footer:
            emb.set_footer(text=footer)
        return emb

    async def _maybe_rename(self, guild: discord.Guild, st: GuildState, ready: bool, seconds_left: int):
        rn = st.rename
        chan_id = rn.get("channel_id")
        if not chan_id:
            return
        channel = guild.get_channel(chan_id)
        if not isinstance(
            channel,
            (discord.TextChannel, discord.VoiceChannel, discord.StageChannel, discord.ForumChannel),
        ):
            return
        try:
            if ready:
                desired = (rn.get("ready_name") or DEFAULT_RENAME["ready_name"])[:100]
            else:
                minutes = max(1, -(-seconds_left // 60))  # ceil
                template = rn.get("cooldown_name") or DEFAULT_RENAME["cooldown_name"]
                desired = template.replace("{minutes}", str(minutes))[:100]
            if channel.name != desired:
                await channel.edit(name=desired, reason="Bremind update")
        except discord.Forbidden:
            pass
        except discord.HTTPException:
            pass

    # ---------- bump detection ----------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild:
            return
        if message.author.id != DISBOARD_BOT_ID:
            return

        # Heuristic for successful bump: DISBOARD typically replies with "Bump done" in content or embed.
        text = (message.content or "").lower()
        embed_text = " ".join([(e.title or "") + " " + (e.description or "") for e in message.embeds]).lower()
        ok = ("bump done" in text) or ("bump done" in embed_text)
        if not ok:
            return

        st = self._state(message.guild.id)
        st.last_bump_ts = int(time.time())
        st.reminder_sent_for_ts = None
        self._persist_all()

        # --- Custom bump reply (if enabled) ---
        if st.bump_reply_template:
            bumper: Optional[discord.abc.User] = None
            if message.interaction and message.interaction.user:
                bumper = message.interaction.user
            elif message.mentions:
                bumper = message.mentions[0]

            minutes = (st.cooldown_s + 59) // 60

            def render_template(tmpl: str) -> str:
                user_mention = bumper.mention if isinstance(bumper, (discord.User, discord.Member)) else "someone"
                user_name = bumper.name if isinstance(bumper, (discord.User, discord.Member)) else "someone"
                try:
                    return tmpl.format(user=user_mention, user_name=user_name, minutes=minutes)
                except Exception:
                    return DEFAULT_BUMP_REPLY.format(user=user_mention, user_name=user_name, minutes=minutes)

            reply = render_template(st.bump_reply_template)
            try:
                await message.channel.send(
                    reply,
                    allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True),
                )
            except discord.HTTPException:
                pass

    # ---------- background tick ----------
    @tasks.loop(seconds=30)
    async def _tick(self):
        now = int(time.time())
        for guild in list(self.bot.guilds):
            st = self._states.get(guild.id)
            if not st or not st.enabled:
                continue

            if st.last_bump_ts is None:
                await self._maybe_rename(guild, st, ready=False, seconds_left=st.cooldown_s)
                continue

            delta = now - st.last_bump_ts
            left = max(0, st.cooldown_s - delta)
            ready = left == 0

            await self._maybe_rename(guild, st, ready=ready, seconds_left=left)

            if ready and st.reminder_sent_for_ts != st.last_bump_ts:
                chan = None
                if st.bump_channel_id:
                    chan = guild.get_channel(st.bump_channel_id)
                if not chan:
                    chan = guild.system_channel
                if not chan:
                    continue

                try:
                    emb = self._build_embed(st)
                    content = None
                    if st.ping_role_id:
                        role = guild.get_role(st.ping_role_id)
                        if role:
                            content = role.mention
                    await chan.send(
                        content=content,
                        embed=emb,
                        allowed_mentions=discord.AllowedMentions(roles=True),
                    )
                    st.reminder_sent_for_ts = st.last_bump_ts
                    self._persist_all()
                except discord.Forbidden:
                    pass
                except discord.HTTPException:
                    pass

    @_tick.before_loop
    async def _before_tick(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(3)

    # ---------- Slash commands ----------
    bremind = app_commands.Group(
        name="bremind",
        description="DISBOARD bump reminder controls",
    )

    # /bremind set-channel also sets rename target and optional templates
    @bremind.command(
        name="set-channel",
        description="Set the reminder channel (also sets auto-rename target and optional templates).",
    )
    @app_commands.describe(
        channel="Channel where reminders will be posted",
        ready_name="(Optional) name when ready, e.g. bump-ready",
        cooldown_name="(Optional) name during cooldown; supports {minutes}",
    )
    async def br_set_channel(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        ready_name: Optional[str] = None,
        cooldown_name: Optional[str] = None,
    ):
        if not interaction.guild:
            return await interaction.response.send_message("Guild only.", ephemeral=True)
        ctx_like = await commands.Context.from_interaction(interaction)
        if not await self._can_manage(ctx_like):
            return await interaction.response.send_message(
                "⛔ You need **Manage Server** or be the bot owner.", ephemeral=True
            )
        st = self._state(interaction.guild.id)
        st.bump_channel_id = channel.id
        st.rename["channel_id"] = channel.id
        if ready_name:
            st.rename["ready_name"] = ready_name[:100]
        if cooldown_name:
            st.rename["cooldown_name"] = cooldown_name[:100]
        self._persist_all()

        pieces = [f"✅ Reminders will go to {channel.mention}.", "Auto-rename will track this channel."]
        if ready_name or cooldown_name:
            pieces.append("Templates updated.")
        await interaction.response.send_message(" ".join(pieces), ephemeral=True)

    @bremind.command(name="set-role", description="Set an optional role to ping on reminder.")
    async def br_set_role(self, interaction: discord.Interaction, role: discord.Role):
        if not interaction.guild:
            return await interaction.response.send_message("Guild only.", ephemeral=True)
        ctx_like = await commands.Context.from_interaction(interaction)
        if not await self._can_manage(ctx_like):
            return await interaction.response.send_message(
                "⛔ You need **Manage Server** or be the bot owner.", ephemeral=True
            )
        st = self._state(interaction.guild.id)
        st.ping_role_id = role.id
        self._persist_all()
        await interaction.response.send_message(f"✅ Will ping {role.mention} on reminder.", ephemeral=True)

    @bremind.command(name="status", description="Show Bremind status and time left.")
    async def br_status(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Guild only.", ephemeral=True)
        st = self._state(interaction.guild.id)
        now = int(time.time())
        if st.last_bump_ts is None:
            left = st.cooldown_s
            ready = False
        else:
            left = max(0, st.cooldown_s - (now - st.last_bump_ts))
            ready = left == 0

        mins = -(-left // 60)  # ceil minutes
        ch = f"<#{st.bump_channel_id}>" if st.bump_channel_id else "—"
        role = f"<@&{st.ping_role_id}>" if st.ping_role_id else "—"
        rn_chan = f"<#{st.rename.get('channel_id')}>" if st.rename.get("channel_id") else "—"

        desc = (
            f"**Enabled:** {st.enabled}\n"
            f"**Ready:** {ready}\n"
            f"**Time left:** {mins} min\n"
            f"**Reminder channel:** {ch}\n"
            f"**Ping role:** {role}\n"
            f"**Rename channel:** {rn_chan}\n"
            f"**Templates:** ready=`{st.rename.get('ready_name')}` "
            f"cooldown=`{st.rename.get('cooldown_name')}`"
        )
        emb = discord.Embed(title="Bremind Status", description=desc, color=0x2B2D31)
        await interaction.response.send_message(embed=emb, ephemeral=True)

    @bremind.command(name="remind-now", description="Send the reminder immediately (ignores cooldown).")
    async def br_remind_now(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Guild only.", ephemeral=True)
        ctx_like = await commands.Context.from_interaction(interaction)
        if not await self._can_manage(ctx_like):
            return await interaction.response.send_message(
                "⛔ You need **Manage Server** or be the bot owner.", ephemeral=True
            )
        st = self._state(interaction.guild.id)
        chan = interaction.guild.get_channel(st.bump_channel_id) if st.bump_channel_id else interaction.guild.system_channel
        if not chan:
            return await interaction.response.send_message("❌ No reminder channel configured.", ephemeral=True)
        emb = self._build_embed(st)
        content = None
        if st.ping_role_id:
            role = interaction.guild.get_role(st.ping_role_id)
            if role:
                content = role.mention
        await chan.send(content=content, embed=emb, allowed_mentions=discord.AllowedMentions(roles=True))
        await interaction.response.send_message("✅ Reminder sent.", ephemeral=True)

    # ---------- EMBED SUBGROUP (RESTORED) ----------
    embed_group = app_commands.Group(
        name="embed",
        description="Customize the reminder embed",
        parent=bremind,
    )

    @embed_group.command(name="edit", description="Open the embed editor (dropdown).")
    async def br_embed_edit(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Guild only.", ephemeral=True)
        ctx_like = await commands.Context.from_interaction(interaction)
        if not await self._can_manage(ctx_like):
            return await interaction.response.send_message(
                "⛔ You need **Manage Server** or be the bot owner.", ephemeral=True
            )
        view = EmbedEditorView(self, interaction.guild.id)
        await interaction.response.send_message(
            "Use the dropdown to customize the reminder embed:", view=view, ephemeral=True
        )

    @embed_group.command(name="show", description="Preview the current reminder embed.")
    async def br_embed_show(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Guild only.", ephemeral=True)
        st = self._state(interaction.guild.id)
        await interaction.response.send_message(embed=self._build_embed(st), ephemeral=True)

    # >>> NEW COMMAND: set-bump-response <<<
    @bremind.command(
        name="set-bump-response",
        description="Set or disable the bot's reply after /bump is used."
    )
    @app_commands.describe(
        template="Custom reply text. Use 'off' to disable, 'default' to reset. Variables: {user}, {user_name}, {minutes}."
    )
    async def br_set_bump_response(self, interaction: discord.Interaction, template: str):
        if not interaction.guild:
            return await interaction.response.send_message("Guild only.", ephemeral=True)
        ctx_like = await commands.Context.from_interaction(interaction)
        if not await self._can_manage(ctx_like):
            return await interaction.response.send_message(
                "⛔ You need **Manage Server** or be the bot owner.", ephemeral=True
            )

        st = self._state(interaction.guild.id)

        t = template.strip()
        tl = t.lower()
        if tl == "off":
            st.bump_reply_template = None
            msg = "✅ Bump reply disabled."
        elif tl == "default":
            st.bump_reply_template = DEFAULT_BUMP_REPLY
            msg = "✅ Bump reply reset to default."
        else:
            st.bump_reply_template = t
            msg = "✅ Bump reply updated."

        self._persist_all()
        await interaction.response.send_message(msg, ephemeral=True)

# ---- setup ----
async def setup(bot: commands.Bot):
    await bot.add_cog(Bremind(bot))