# cogs/embedgen.py
from __future__ import annotations
import json
from pathlib import Path
from typing import Optional, Dict, Any, List

import discord
from discord.ext import commands
from discord import app_commands

# ---------- tiny storage ----------
DATA_DIR = Path("data")
STORE_FILE = DATA_DIR / "embedgen.json"

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

def _save_store(store: Dict[str, Any]):
    _ensure_store()
    STORE_FILE.write_text(json.dumps(store, indent=2), encoding="utf-8")

def _g(store: Dict[str, Any], gid: int) -> Dict[str, Any]:
    key = str(gid)
    store.setdefault("guilds", {})
    store["guilds"].setdefault(key, {"allowed_role_ids": []})
    return store["guilds"][key]

def _member_has_allowed_role(member: discord.Member, allowed_ids: List[int]) -> bool:
    if not allowed_ids:
        # default: restrict to admins only if no roles configured
        return member.guild_permissions.manage_guild
    m_ids = {r.id for r in member.roles}
    return any(rid in m_ids for rid in allowed_ids)

def _role_gate(store: Dict[str, Any]):
    async def predicate(ctx: commands.Context) -> bool:
        if ctx.guild is None or not isinstance(ctx.author, discord.Member):
            return False
        allowed = [int(x) for x in _g(store, ctx.guild.id).get("allowed_role_ids", [])]
        if not _member_has_allowed_role(ctx.author, allowed):
            raise commands.CheckFailure("You are not allowed to use embed commands.")
        return True
    return commands.check(predicate)

# ---------- helpers ----------
def _parse_hex(hexstr: str) -> Optional[discord.Color]:
    if not hexstr:
        return None
    raw = hexstr.strip().lstrip("#")
    try:
        return discord.Color(int(raw, 16))
    except ValueError:
        return None

async def _ensure_can_send(ctx: commands.Context, channel: discord.abc.Messageable) -> bool:
    if not isinstance(channel, (discord.TextChannel, discord.Thread, discord.VoiceChannel, discord.StageChannel)):
        await ctx.reply("❌ Please choose a text channel (or thread).", mention_author=False)
        return False
    perms = channel.permissions_for(ctx.author)
    if not (perms.manage_messages or perms.manage_channels or perms.administrator):
        await ctx.reply("❌ You need **Manage Messages** (or higher) in that channel.", mention_author=False)
        return False
    bperms = channel.permissions_for(ctx.guild.me) if ctx.guild else None
    if not (bperms and bperms.send_messages and bperms.embed_links):
        await ctx.reply("❌ I need **Send Messages** and **Embed Links** in that channel.", mention_author=False)
        return False
    return True

# ---------- modal ----------
class EmbedModal(discord.ui.Modal, title="Create an embed"):
    def __init__(self, interaction: discord.Interaction, channel: discord.TextChannel | discord.Thread):
        super().__init__()
        self.target = channel
        self.inter = interaction

        self.title_inp = discord.ui.TextInput(label="Title", max_length=256, required=False)
        self.add_item(self.title_inp)

        self.desc_inp = discord.ui.TextInput(
            label="Description", style=discord.TextStyle.paragraph, required=False
        )
        self.add_item(self.desc_inp)

        self.color_inp = discord.ui.TextInput(label="Color HEX (#5865F2)", required=False, max_length=7)
        self.add_item(self.color_inp)

        self.image_inp = discord.ui.TextInput(label="Image URL", required=False)
        self.add_item(self.image_inp)

        self.footer_inp = discord.ui.TextInput(label="Footer text", max_length=2048, required=False)
        self.add_item(self.footer_inp)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        emb = discord.Embed()
        if self.title_inp.value:
            emb.title = self.title_inp.value
        if self.desc_inp.value:
            emb.description = self.desc_inp.value
        if self.color_inp.value:
            c = _parse_hex(self.color_inp.value)
            if c:
                emb.color = c
        if self.image_inp.value:
            emb.set_image(url=self.image_inp.value.strip())
        if self.footer_inp.value:
            emb.set_footer(text=self.footer_inp.value.strip())

        await self.target.send(embed=emb)
        await interaction.response.send_message("✅ Embed sent.", ephemeral=True)

# ---------- cog ----------
class EmbedGen(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.store = _load_store()

    async def cog_load(self):
        gate = _role_gate(self.store)
        self.embed.add_check(gate)
        self.embededit.add_check(gate)

    @commands.hybrid_command(name="embed", description="Open a modal to create an embed.")
    @app_commands.describe(channel="Where to post the embed (defaults to current channel)")
    @commands.guild_only()
    async def embed(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None):
        target = channel or ctx.channel
        if not await _ensure_can_send(ctx, target):
            return
        if ctx.interaction:
            await ctx.interaction.response.send_modal(EmbedModal(ctx.interaction, target))
        else:
            await ctx.reply("Use `/embed` slash command to open the modal.", delete_after=6)

    @commands.hybrid_command(name="embededit", description="Edit an existing embed by message ID.")
    @app_commands.describe(
        message_id="Message ID",
        channel="Channel (defaults to current)",
        title="New title",
        description="New description",
        color_hex="New color HEX",
        image_url="New image URL",
        footer_text="New footer text",
    )
    @commands.guild_only()
    async def embededit(
        self,
        ctx: commands.Context,
        message_id: int,
        channel: Optional[discord.TextChannel] = None,
        title: Optional[str] = None,
        description: Optional[str] = None,
        color_hex: Optional[str] = None,
        image_url: Optional[str] = None,
        footer_text: Optional[str] = None,
    ):
        target = channel or ctx.channel
        if not await _ensure_can_send(ctx, target):
            return
        try:
            msg = await target.fetch_message(message_id)
        except Exception:
            return await ctx.reply("❌ Message not found.", mention_author=False)

        emb = msg.embeds[0] if msg.embeds else discord.Embed()
        if title is not None:
            emb.title = title or discord.Embed.Empty
        if description is not None:
            emb.description = description or discord.Embed.Empty
        if color_hex is not None:
            col = _parse_hex(color_hex)
            if col:
                emb.color = col
        if image_url is not None:
            emb.set_image(url=image_url.strip() or None)
        if footer_text is not None:
            emb.set_footer(text=footer_text.strip() or None)

        await msg.edit(embed=emb)
        if ctx.interaction:
            await ctx.interaction.response.send_message("✅ Embed updated.", ephemeral=True)
        else:
            await ctx.message.add_reaction("✅")

    # ---- role management ----
    @commands.hybrid_command(name="embed_addrole", description="Allow a role to use embed commands.")
    @commands.has_permissions(manage_guild=True)
    async def embed_addrole(self, ctx: commands.Context, role: discord.Role):
        gcfg = _g(self.store, ctx.guild.id)
        ids = set(int(x) for x in gcfg.get("allowed_role_ids", []))
        ids.add(role.id)
        gcfg["allowed_role_ids"] = list(ids)
        _save_store(self.store)
        await ctx.reply(f"✅ {role.mention} added to embed allow-list.", mention_author=False)

    @commands.hybrid_command(name="embed_removerole", description="Remove a role from the embed allow-list.")
    @commands.has_permissions(manage_guild=True)
    async def embed_removerole(self, ctx: commands.Context, role: discord.Role):
        gcfg = _g(self.store, ctx.guild.id)
        ids = set(int(x) for x in gcfg.get("allowed_role_ids", []))
        if role.id in ids:
            ids.remove(role.id)
            gcfg["allowed_role_ids"] = list(ids)
            _save_store(self.store)
            await ctx.reply(f"🗑️ {role.mention} removed from embed allow-list.", mention_author=False)
        else:
            await ctx.reply(f"{role.mention} wasn’t on the allow-list.", mention_author=False)

    @commands.hybrid_command(name="embed_listroles", description="List roles allowed for embed commands.")
    @commands.has_permissions(manage_guild=True)
    async def embed_listroles(self, ctx: commands.Context):
        gcfg = _g(self.store, ctx.guild.id)
        ids = [int(x) for x in gcfg.get("allowed_role_ids", [])]
        if not ids:
            return await ctx.reply("Default: only admins (Manage Guild) can use embed commands.", mention_author=False)
        roles = [ctx.guild.get_role(rid) for rid in ids]
        mentions = [r.mention for r in roles if r]
        await ctx.reply("Allowed roles: " + (", ".join(mentions) if mentions else "(no valid roles)"), mention_author=False)

async def setup(bot: commands.Bot):
    await bot.add_cog(EmbedGen(bot))