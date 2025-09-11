# cogs/stealemoji.py
from __future__ import annotations
import re
from typing import Optional, List, Tuple

import aiohttp
import discord
from discord.ext import commands

EMOJI_SIZE_LIMIT = 256 * 1024  # 256 KB
NAME_ALLOWED = re.compile(r"[^0-9a-zA-Z_]+")

def sanitize_name(name: str) -> str:
    name = NAME_ALLOWED.sub("_", (name or "").strip())
    return name[:32] or "emoji"

def parse_custom_emojis(text: str) -> List[discord.PartialEmoji]:
    found: List[discord.PartialEmoji] = []
    for token in re.findall(r"<a?:[A-Za-z0-9_]+:\d+>", text):
        try:
            pe = discord.PartialEmoji.from_str(token)
            if pe and pe.id:
                found.append(pe)
        except Exception:
            continue
    if not found:
        for token in text.split():
            try:
                pe = discord.PartialEmoji.from_str(token)
                if pe and pe.id:
                    found.append(pe)
            except Exception:
                pass
    return found

async def _fetch_emoji_bytes(bot: commands.Bot, pe: discord.PartialEmoji) -> tuple[bytes | None, str | None]:
    """
    Try multiple strategies to fetch emoji bytes.
    Returns (data, error_reason). If data is None, error_reason is a human string.
    """
    # 1) Newer discord.py: PartialEmoji.read()
    try:
        if hasattr(pe, "read"):
            data = await pe.read()
            if data:
                return data, None
    except discord.NotFound:
        return None, "Image not found (404)"
    except discord.HTTPException as e:
        return None, f"HTTP error via library: {e.status if hasattr(e, 'status') else e}"
    except Exception as e:
        # fall through to URL attempts
        pass

    # 2) Asset read (older versions): pe.url.read()
    try:
        url_obj = getattr(pe, "url", None)
        if url_obj:
            data = await url_obj.read()
            if data:
                return data, None
    except discord.NotFound:
        return None, "Image not found (404)"
    except discord.HTTPException as e:
        # keep going; try CDN raw
        pass
    except Exception:
        pass

    # 3) Raw CDN URL (GIF first if animated, then PNG)
    base = f"https://cdn.discordapp.com/emojis/{pe.id}"
    candidates = [f"{base}.gif?size=96&quality=lossless"] if pe.animated else []
    candidates.append(f"{base}.png?size=96&quality=lossless")

    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        last_status = None
        for url in candidates:
            try:
                async with session.get(url, headers={"User-Agent": "stealemoji/1.0"}) as resp:
                    last_status = resp.status
                    if resp.status == 200:
                        data = await resp.read()
                        if data:
                            return data, None
                    elif resp.status == 404:
                        # try next candidate
                        continue
                    else:
                        # keep last status to report
                        continue
            except aiohttp.ClientError as e:
                return None, f"Network error: {type(e).__name__}"
            except Exception as e:
                return None, f"Unexpected fetch error: {type(e).__name__}"

    return None, f"CDN refused (status {last_status})" if last_status else "Could not reach CDN"

class StealEmoji(commands.Cog):
    """Steal one or multiple custom emojis into this server."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(
        name="steal",
        description="Steal one or more custom emojis into this server. Usage: !steal <emoji...> [name_prefix]"
    )
    @commands.has_permissions(manage_emojis=True)
    @commands.bot_has_permissions(manage_emojis=True)
    async def steal(self, ctx: commands.Context, *, emojis_and_prefix: str):
        if ctx.guild is None:
            return await self._reply(ctx, "This command can only be used in a server.", ephemeral=True)

        text = (emojis_and_prefix or "").strip()
        if not text:
            return await self._reply(ctx, "Provide at least one custom emoji to steal.", ephemeral=True)

        # Detect optional trailing prefix
        tokens = text.split()
        last = tokens[-1] if tokens else ""
        is_emoji_token = bool(re.fullmatch(r"<a?:[A-Za-z0-9_]+:\d+>", last))
        name_prefix = "" if is_emoji_token else sanitize_name(last)
        emoji_str = text if is_emoji_token else " ".join(tokens[:-1]) if len(tokens) > 1 else ""

        emojis = parse_custom_emojis(emoji_str or text)  # fallback to full text if needed
        if not emojis:
            return await self._reply(
                ctx, "I couldn't find any **custom emoji**. Example: `<:name:123456789012345678>`", ephemeral=True
            )

        # Check emoji slots
        limit = getattr(ctx.guild, "emoji_limit", 50)
        free_slots = max(0, limit - len(ctx.guild.emojis))
        if free_slots <= 0:
            return await self._reply(ctx, f"No emoji slots left (limit: {limit}).", ephemeral=True)

        successes: list[discord.Emoji] = []
        failures: list[Tuple[str, str]] = []

        for idx, pe in enumerate(emojis, start=1):
            if len(successes) >= free_slots:
                failures.append((str(pe), "No slots left"))
                continue

            name = f"{name_prefix}{idx}" if name_prefix else sanitize_name(pe.name or f"emoji_{pe.id}")

            data, err = await _fetch_emoji_bytes(self.bot, pe)
            if err or not data:
                failures.append((str(pe), err or "Unknown download error"))
                continue

            if len(data) > EMOJI_SIZE_LIMIT:
                failures.append((str(pe), f"Too large ({len(data)//1024} KB > 256 KB)"))
                continue

            try:
                created = await ctx.guild.create_custom_emoji(name=name, image=data, reason=f"Stolen by {ctx.author}")
                successes.append(created)
            except discord.Forbidden:
                failures.append((str(pe), "Missing Manage Emojis permission"))
            except discord.HTTPException as e:
                failures.append((str(pe), f"Upload rejected: {e}"))

        # Build result message
        if successes and not failures:
            msg = "✅ Added: " + " ".join(str(e) for e in successes)
        elif successes and failures:
            skipped = "; ".join(f"`{disp}` → {why}" for disp, why in failures)
            msg = f"✅ Added: {' '.join(str(e) for e in successes)}\n⚠️ Skipped: {skipped}"
        else:
            skipped = "; ".join(f"`{disp}` → {why}" for disp, why in failures) or "unknown"
            msg = f"❌ Couldn't add any emojis. Reasons: {skipped}"

        await self._reply(ctx, msg, ephemeral=False)

    async def _reply(
        self,
        ctx: commands.Context,
        content: Optional[str] = None,
        *,
        embed: Optional[discord.Embed] = None,
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
    await bot.add_cog(StealEmoji(bot))