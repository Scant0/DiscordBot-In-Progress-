# cogs/presence.py
from __future__ import annotations
from typing import Optional, List, Tuple, Literal
import json
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands, tasks

# --- Role restriction ---
ADMIN_ROLE_IDS = {1415420040366526656}  # replace with your Admin role ID(s)

# --------- Persistence paths ---------
DATA_DIR = Path("data")
ROT_FILE = DATA_DIR / "presence_rotation.json"

def _ensure_store():
    DATA_DIR.mkdir(exist_ok=True)
    if not ROT_FILE.exists():
        ROT_FILE.write_text(
            json.dumps(
                {
                    "rotation": [],
                    "interval": 60,
                    "status": "online",
                    "activity": None,     # {"type": "...", "text": "...", "url": "..."}
                    "autostart": False,   # user preference
                    "rotating": False,    # last known running state (for resume)
                },
                indent=2,
            ),
            encoding="utf-8",
        )

def _load_state() -> tuple[
    list[tuple[str, str, Optional[str]]],  # rotation
    int,                                   # interval
    str,                                   # status
    Optional[tuple[str, str, Optional[str]]],  # activity
    bool,                                  # autostart
    bool,                                  # rotating
]:
    try:
        _ensure_store()
        raw = json.loads(ROT_FILE.read_text(encoding="utf-8"))

        # rotation
        rot_items: list[tuple[str, str, Optional[str]]] = []
        for item in raw.get("rotation", []):
            at = str(item.get("type", "playing")).lower().strip()
            text = str(item.get("text", "")).strip()
            url = item.get("url")
            url = str(url) if url else None
            if text:
                rot_items.append((at, text, url))

        interval = max(10, int(raw.get("interval", 60)))

        status = str(raw.get("status", "online")).lower().strip()
        if status not in {"online", "idle", "dnd", "invisible"}:
            status = "online"

        act_raw = raw.get("activity")
        if isinstance(act_raw, dict):
            at = str(act_raw.get("type", "playing")).lower().strip()
            text = str(act_raw.get("text", "")).strip()
            url = act_raw.get("url")
            url = str(url) if url else None
            activity = (at, text, url) if text else None
        else:
            activity = None

        autostart = bool(raw.get("autostart", False))
        rotating = bool(raw.get("rotating", False))

        return rot_items, interval, status, activity, autostart, rotating
    except Exception:
        return [], 60, "online", None, False, False

def _save_state(
    rotation: list[tuple[str, str, Optional[str]]],
    interval: int,
    status: str,
    activity: Optional[tuple[str, str, Optional[str]]],
    autostart: bool,
    rotating: bool,
) -> None:
    try:
        _ensure_store()
        payload = {
            "rotation": [{"type": at, "text": text, "url": url} for (at, text, url) in rotation],
            "interval": max(10, int(interval)),
            "status": status,
            "activity": (
                {"type": activity[0], "text": activity[1], "url": activity[2]}
                if activity and activity[1]
                else None
            ),
            "autostart": autostart,
            "rotating": rotating,
        }
        ROT_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass

# --------- Status / Activity maps ---------
STATUS_MAP = {
    "online": discord.Status.online,
    "idle": discord.Status.idle,
    "dnd": discord.Status.do_not_disturb,
    "invisible": discord.Status.invisible,
    "offline": discord.Status.invisible,  # alias
}

ACTIVITY_TYPE_MAP = {
    "playing": discord.ActivityType.playing,
    "listening": discord.ActivityType.listening,
    "watching": discord.ActivityType.watching,
    "competing": discord.ActivityType.competing,
    "streaming": discord.ActivityType.streaming,
}

def norm(s: Optional[str]) -> Optional[str]:
    return s.lower().strip() if isinstance(s, str) else None

class Presence(commands.Cog):
    """
    Presence manager with persistence, rotation, autostart toggle,
    and resume-last-rotation behavior.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # Load persisted state
        rotation, interval, status_str, activity_tup, autostart, rotating = _load_state()
        self._rotation: List[Tuple[str, str, Optional[str]]] = rotation
        self._rot_index: int = 0
        self._rot_interval: int = interval
        self._autostart: bool = autostart
        self._was_rotating_last_time: bool = rotating  # last saved state

        # Current status & activity
        self._status_str: str = status_str
        self._current_status: discord.Status = STATUS_MAP[status_str]
        self._activity_tup: Optional[tuple[str, str, Optional[str]]] = activity_tup
        self._current_activity: Optional[discord.BaseActivity] = (
            self._build_activity(*activity_tup) if activity_tup else None
        )

        # Rotation task
        self._rot_task_running = False
        self._rotator_loop.change_interval(seconds=self._rot_interval)

    # ---------------- Perms / Replies ----------------

    async def _can_use(self, ctx: commands.Context) -> bool:
        if await self.bot.is_owner(ctx.author):
            return True
        if isinstance(ctx.author, discord.Member):
            perms = ctx.channel.permissions_for(ctx.author)
            return perms.manage_guild
        return False

    async def _reply(self, ctx: commands.Context, text: str, ephemeral=True):
        if getattr(ctx, "interaction", None):
            if not ctx.interaction.response.is_done():
                await ctx.interaction.response.send_message(text, ephemeral=ephemeral)
            else:
                await ctx.interaction.followup.send(text, ephemeral=ephemeral)
        else:
            await ctx.reply(text, mention_author=False)

    # ---------------- Lifecycle ----------------

    @commands.Cog.listener()
    async def on_ready(self):
        try:
            await self.bot.change_presence(status=self._current_status, activity=self._current_activity)
        except Exception:
            pass
        print(f"[presence] ready — status: {self._status_str} | activity: {self._activity_tup}")
        print(f"[presence] rotation items: {len(self._rotation)} | interval: {self._rot_interval}s | "
              f"autostart: {self._autostart} | last rotating: {self._was_rotating_last_time}")

        # Auto-start rotation if enabled OR if last session had rotation running
        if (self._autostart or self._was_rotating_last_time) and self._rotation and not self._rotator_loop.is_running():
            self._rotator_loop.change_interval(seconds=self._rot_interval)
            self._rotator_loop.start()
            self._rot_task_running = True
            self._persist()  # save running state
            print("[presence] rotation loop started on boot")

    @commands.Cog.listener()
    async def on_disconnect(self):
        # Best-effort save on disconnect/shutdown
        self._persist()

    def cog_unload(self):
        # Persist on unload as well
        self._persist()
        if self._rotator_loop.is_running():
            self._rotator_loop.cancel()

    # ---------------- Helpers ----------------

    def _build_activity(self, activity_type: str, text: str, url: Optional[str] = None) -> discord.BaseActivity:
        at = norm(activity_type)
        if at == "playing":
            return discord.Game(name=text)
        if at == "streaming":
            return discord.Streaming(name=text, url=url or "https://twitch.tv/example")
        t = ACTIVITY_TYPE_MAP.get(at or "playing", discord.ActivityType.playing)
        return discord.Activity(type=t, name=text)

    async def _apply_presence(self):
        try:
            await self.bot.change_presence(status=self._current_status, activity=self._current_activity)
        except discord.HTTPException:
            pass

    def _persist(self):
        rotating = self._rotator_loop.is_running()
        _save_state(self._rotation, self._rot_interval, self._status_str, self._activity_tup, self._autostart, rotating)

    # ---------------- Rotation loop ----------------

    @tasks.loop(seconds=60)
    async def _rotator_loop(self):
        if not self._rotation:
            return
        self._rot_index %= len(self._rotation)
        a_type, text, url = self._rotation[self._rot_index]
        self._rot_index = (self._rot_index + 1) % len(self._rotation)
        self._activity_tup = (a_type, text, url)
        self._current_activity = self._build_activity(a_type, text, url)
        self._persist()
        await self._apply_presence()

    @_rotator_loop.before_loop
    async def _before_rot(self):
        await self.bot.wait_until_ready()

    # ---------------- Auto-start toggle ----------------

    @commands.hybrid_command(name="rotautostart", description="Toggle auto-start of rotation on bot startup.")
    async def rotautostart(self, ctx: commands.Context, state: Literal["on", "off"]):
        if not await self._can_use(ctx):
            return await self._reply(ctx, "⛔ You need **Manage Server** or be the bot owner.")
        self._autostart = state == "on"
        self._persist()
        await self._reply(ctx, f"🔁 Auto-start on boot is now **{state.upper()}**.")

    # ---------------- Core presence commands ----------------

    @commands.hybrid_command(name="setstatus", description="Set the bot's status: online/idle/dnd/invisible.")
    async def setstatus(
        self,
        ctx: commands.Context,
        status: Literal["online", "idle", "dnd", "invisible"],
    ):
        if not await self._can_use(ctx):
            return await self._reply(ctx, "⛔ You need **Manage Server** or be the bot owner.")
        self._status_str = status
        self._current_status = STATUS_MAP[status]
        self._persist()
        await self._apply_presence()
        await self._reply(ctx, f"✅ Status set to **{status}**.")

    @commands.hybrid_command(
        name="setactivity",
        description="Set a single activity. Stops rotation."
    )
    async def setactivity(
        self,
        ctx: commands.Context,
        activity_type: Literal["playing", "listening", "watching", "competing", "streaming"],
        *, text: str
    ):
        if not await self._can_use(ctx):
            return await self._reply(ctx, "⛔ You need **Manage Server** or be the bot owner.")
        if self._rotator_loop.is_running():
            self._rotator_loop.cancel()
            self._rot_task_running = False
        self._activity_tup = (activity_type, text, "https://twitch.tv/example" if activity_type == "streaming" else None)
        self._current_activity = self._build_activity(*self._activity_tup)
        self._persist()
        await self._apply_presence()
        await self._reply(ctx, f"✅ Activity set: **{activity_type}** {text!r} (rotation stopped)")

    @commands.hybrid_command(name="clearactivity", description="Clear the bot's activity (keeps current status).")
    async def clearactivity(self, ctx: commands.Context):
        if not await self._can_use(ctx):
            return await self._reply(ctx, "⛔ You need **Manage Server** or be the bot owner.")
        if self._rotator_loop.is_running():
            self._rotator_loop.cancel()
            self._rot_task_running = False
        self._activity_tup = None
        self._current_activity = None
        self._persist()
        await self._apply_presence()
        await self._reply(ctx, "🧹 Activity cleared (rotation stopped).")

    @commands.hybrid_command(name="presence", description="Show the current status/activity.")
    async def presence(self, ctx: commands.Context):
        act = self._current_activity
        if isinstance(act, discord.Streaming):
            act_str = f"Streaming: {act.name} ({act.url})"
        elif isinstance(act, discord.Game):
            act_str = f"Playing: {act.name}"
        elif isinstance(act, discord.Activity):
            act_str = f"{act.type.name.title()}: {act.name}"
        else:
            act_str = "None"
        await self._reply(ctx, f"📟 Status: **{self._status_str}**\n🎮 Activity: **{act_str}**")

    # ---------------- Rotation commands (persisted) ----------------

    @commands.hybrid_command(
        name="rotstart",
        description="Start rotating activities every N seconds (default 60)."
    )
    @app_commands.describe(interval_seconds="How often to rotate (seconds)")
    async def rotstart(self, ctx: commands.Context, interval_seconds: Optional[int] = 60):
        if not await self._can_use(ctx):
            return await self._reply(ctx, "⛔ You need **Manage Server** or be the bot owner.")
        if not self._rotation:
            return await self._reply(ctx, "ℹ️ Rotation list is empty. Add items with `/rotadd` first.")
        interval = max(10, int(interval_seconds or 60))
        self._rot_interval = interval
        self._rotator_loop.change_interval(seconds=interval)
        if not self._rotator_loop.is_running():
            self._rotator_loop.start()
        self._rot_task_running = True
        self._persist()
        await self._reply(ctx, f"▶️ Rotating every **{interval}s** with **{len(self._rotation)}** item(s).")

    @rotstart.autocomplete("interval_seconds")
    async def rotstart_interval_ac(self, interaction: discord.Interaction, current: str):
        common = [10, 15, 30, 45, 60, 90, 120, 300]
        return [app_commands.Choice(name=f"{n} seconds", value=n) for n in common]

    @commands.hybrid_command(name="rotstop", description="Stop rotating activities (keeps current activity).")
    async def rotstop(self, ctx: commands.Context):
        if not await self._can_use(ctx):
            return await self._reply(ctx, "⛔ You need **Manage Server** or be the bot owner.")
        if self._rotator_loop.is_running():
            self._rotator_loop.cancel()
        self._rot_task_running = False
        self._persist()
        await self._reply(ctx, "⏹️ Rotation stopped. Current activity left as-is.")

    @commands.hybrid_command(
        name="rotadd",
        description="Add an item to rotation. Example: /rotadd playing 'Minecraft'"
    )
    async def rotadd(
        self,
        ctx: commands.Context,
        activity_type: Literal["playing", "listening", "watching", "competing", "streaming"],
        *, text: str
    ):
        if not await self._can_use(ctx):
            return await self._reply(ctx, "⛔ You need **Manage Server** or be the bot owner.")
        at = norm(activity_type) or "playing"
        url = "https://twitch.tv/example" if at == "streaming" else None
        self._rotation.append((at, text, url))
        self._persist()
        await self._reply(ctx, f"➕ Added to rotation: **{at}** {text!r} (now {len(self._rotation)} item(s)).")

    @commands.hybrid_command(name="rotlist", description="List rotation items.")
    async def rotlist(self, ctx: commands.Context):
        if not await self._can_use(ctx):
            return await self._reply(ctx, "⛔ You need **Manage Server** or be the bot owner.")
        if not self._rotation:
            return await self._reply(ctx, "(empty rotation)")
        lines = []
        for i, (at, text, url) in enumerate(self._rotation, 1):
            extra = f" [{url}]" if at == "streaming" and url else ""
            lines.append(f"{i}. **{at}** — {text}{extra}")
        await self._reply(ctx, "\n".join(lines))

    @commands.hybrid_command(name="rotdel", description="Remove a rotation item by number (see /rotlist).")
    @app_commands.describe(index="Pick an item number to remove")
    async def rotdel(self, ctx: commands.Context, index: int):
        if not await self._can_use(ctx):
            return await self._reply(ctx, "⛔ You need **Manage Server** or be the bot owner.")
        if index < 1 or index > len(self._rotation):
            return await self._reply(ctx, "❌ Invalid index. Use `/rotlist` to see numbers.")
        removed = self._rotation.pop(index - 1)
        self._persist()
        await self._reply(ctx, f"🗑️ Removed item {index}: **{removed[0]}** {removed[1]!r}")

    @rotdel.autocomplete("index")
    async def rotdel_index_ac(self, interaction: discord.Interaction, current: str):
        choices: list[app_commands.Choice[int]] = []
        for i, (at, text, url) in enumerate(self._rotation, 1):
            label = f"{i}. {at} — {text[:60]}"
            choices.append(app_commands.Choice(name=label, value=i))
            if len(choices) >= 25:
                break
        return choices

async def setup(bot: commands.Bot):
    await bot.add_cog(Presence(bot))