# =============================
# helpers.py (refactored)
# =============================
import os
import asyncio
import json
import sqlite3
import re
from datetime import datetime, timezone, date
from typing import List, Optional, Union, Any, Dict, Tuple

import discord
from discord.ext import commands
from dotenv import load_dotenv
load_dotenv()
# ─── Database Path ─────────────────────────────
#DB_PATH = "/data/rocket.db"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "rocket.db")

# ─── Daily Limits ─────────────────────────────
ADMIN_DATE_LIMIT_PER_DAY = 5
USER_DATE_LIMIT_PER_DAY = 3

# ─── DB Init ─────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Single source of truth for all e-date activity
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS e_date_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER,
            date TEXT,                  -- UTC date (YYYY-MM-DD)
            user_id INTEGER,            -- receiver/target of the e-date
            e_date_sender_id INTEGER,   -- initiator/sender of the e-date
            status TEXT,                -- 'pending' | 'yes' | 'no'
            reason TEXT,                -- optional reason on reject
            timestamp TEXT              -- full ISO timestamp
        )
        """
    )
    conn.commit()
    conn.close()

# ─── Role-based checks ─────────────────────────────
def is_edate_gamer(member: discord.Member) -> bool:
    """Return True if member has either PokeCandidates or TEAM ROCKET roles."""
    role_names = {r.name.lower() for r in member.roles}
    allowed_roles = {"team rocket","catching pokemen", "catching pokewomen", "catching 'em all"}
    return bool(role_names & allowed_roles)  # True if at least one matches


def get_gender_emoji(member: discord.Member) -> str:
    role_names = {r.name.lower() for r in member.roles}
    if "rocket pokewoman ♀️" in role_names:
        return "♀️"
    if "rocket pokeman ♂️" in role_names:
        return "♂️"
    if "rocket pokepal ⚧" in role_names:
        return "⚧"
    return "❓"


def get_guild_contestants(guild: discord.Guild) -> list[discord.Member]:
    """Return all members in the guild who have at least one Catching role."""
    catch_role_names = {"Catching PokeMen", "Catching PokeWomen", "Catching 'em all","Team Rocket"}

    # Map role names to actual role objects
    catch_roles = {role for role in guild.roles if role.name in catch_role_names}
    if not catch_roles:
        return []

    # Return members with at least one catch role (excluding bots)
    return [
        member for member in guild.members
        if not member.bot and any(role in member.roles for role in catch_roles)
    ]


# ─── Time helpers ─────────────────────────────
def utc_today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()

# ─── Records helpers ─────────────────────────────
def count_sent_today(guild_id: int, sender_id: int) -> int:
    today = utc_today_str()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        SELECT COUNT(*) FROM e_date_records
        WHERE guild_id=? AND e_date_sender_id=? AND date=?
        """,
        (guild_id, sender_id, today)
    )
    (count,) = c.fetchone()
    conn.close()
    return int(count or 0)


def insert_record(guild_id: int, user_id: int, sender_id: int) -> None:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO e_date_records (guild_id, date, user_id, e_date_sender_id, status, reason, timestamp)
        VALUES (?, ?, ?, ?, 'pending', '', ?)
        """,
        (guild_id, utc_today_str(), user_id, sender_id, iso_now())
    )
    conn.commit()
    conn.close()


def get_pending_between(guild_id: int, sender_id: int, receiver_id: int) -> Optional[int]:
    """Return record id of a pending request from sender->receiver, else None."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        SELECT id FROM e_date_records
        WHERE guild_id=? AND e_date_sender_id=? AND user_id=? AND status='pending'
        ORDER BY id DESC LIMIT 1
        """,
        (guild_id, sender_id, receiver_id)
    )
    row = c.fetchone()
    conn.close()
    return row[0] if row else None


def update_status(record_id: int, status: str, reason: str = "") -> None:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "UPDATE e_date_records SET status=?, reason=? WHERE id=?",
        (status, reason, record_id)
    )
    conn.commit()
    conn.close()


def fetch_incoming_history(guild_id: int, receiver_id: int) -> List[Tuple[str, int, str, str]]:
    """Return list of (date, sender_id, status, reason) for a receiver, newest first."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        SELECT date, e_date_sender_id, status, reason
        FROM e_date_records
        WHERE guild_id=? AND user_id=?
        ORDER BY timestamp DESC
        """,
        (guild_id, receiver_id)
    )
    rows = c.fetchall()
    conn.close()
    return rows


def compute_points(guild: discord.Guild) -> Dict[int, int]:
    """Compute dynamic points per user: +1 for each accepted ('yes') participation
    (both sender and receiver earn a point per accepted record)."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT user_id FROM e_date_records WHERE guild_id=? AND status='yes'",
        (guild.id,)
    )
    recv_rows = [r[0] for r in c.fetchall()]
    c.execute(
        "SELECT e_date_sender_id FROM e_date_records WHERE guild_id=? AND status='yes'",
        (guild.id,)
    )
    send_rows = [r[0] for r in c.fetchall()]
    conn.close()

    points: Dict[int, int] = {}
    for uid in recv_rows + send_rows:
        points[uid] = points.get(uid, 0) + 1

    # Keep only members with the right roles
    valid_ids = {m.id for m in get_guild_contestants(guild)}
    return {uid: pts for uid, pts in points.items() if uid in valid_ids}

# ─── Messaging & Pagination ─────────────────────────────
async def safe_send(ctx: Union[commands.Context, discord.Interaction], content: str = None, embed=None, view=None, ephemeral=False):
    try:
        if isinstance(ctx, discord.Interaction):
            if ctx.response.is_done():
                await ctx.followup.send(content=content, embed=embed, view=view, ephemeral=ephemeral)
            else:
                await ctx.response.send_message(content=content, embed=embed, view=view, ephemeral=ephemeral)
        else:
            await ctx.send(content=content, embed=embed, view=view)
    except discord.Forbidden:
        pass

class TextPaginator(discord.ui.View):
    def __init__(self, pages: List[str], color=discord.Color.blurple()):
        super().__init__(timeout=None)
        self.pages = pages
        self.current = 0
        self.embed = discord.Embed(description=self.pages[self.current], color=color)
        self.message = None
        self.add_item(self.PrevButton(self))
        self.add_item(self.NextButton(self))

    async def start(self, ctx: Union[commands.Context, discord.Interaction]):
        if isinstance(ctx, discord.Interaction):
            await ctx.response.send_message(embed=self.embed, view=self)
            self.message = await ctx.original_response()
        else:
            self.message = await ctx.send(embed=self.embed, view=self)

    class PrevButton(discord.ui.Button):
        def __init__(self, parent):
            super().__init__(label="◀️", style=discord.ButtonStyle.primary)
            self.parent = parent
        async def callback(self, interaction: discord.Interaction):
            self.parent.current = (self.parent.current - 1) % len(self.parent.pages)
            self.parent.embed.description = self.parent.pages[self.parent.current]
            await interaction.response.edit_message(embed=self.parent.embed, view=self.parent)

    class NextButton(discord.ui.Button):
        def __init__(self, parent):
            super().__init__(label="▶️", style=discord.ButtonStyle.primary)
            self.parent = parent
        async def callback(self, interaction: discord.Interaction):
            self.parent.current = (self.parent.current + 1) % len(self.parent.pages)
            self.parent.embed.description = self.parent.pages[self.parent.current]
            await interaction.response.edit_message(embed=self.parent.embed, view=self.parent)

class EmbedPaginator(discord.ui.View):
    """Embed paginator that works with both prefix and slash commands."""

    def __init__(self, embeds: List[discord.Embed], author: discord.User, timeout: int = 120):
        super().__init__(timeout=timeout)
        self.embeds = embeds
        self.index = 0
        self.message: discord.Message = None
        self.author = author  # only allow the command caller

        # total pages for footer
        self.total_pages = len(embeds)

        # add page numbers to all embeds
        for idx, embed in enumerate(self.embeds, start=1):
            if embed.footer and embed.footer.text:
                embed.set_footer(text=f"{embed.footer.text} | Page {idx}/{self.total_pages}")
            else:
                embed.set_footer(text=f"Page {idx}/{self.total_pages}")

    async def start(self, ctx_or_interaction: Union[commands.Context, discord.Interaction]):
        """Send the first embed and attach the paginator."""
        first_embed = self.embeds[self.index]

        if isinstance(ctx_or_interaction, commands.Context):  # Prefix command
            self.message = await ctx_or_interaction.send(embed=first_embed, view=self)

        elif isinstance(ctx_or_interaction, discord.Interaction):  # Slash command
            if ctx_or_interaction.response.is_done():
                self.message = await ctx_or_interaction.followup.send(embed=first_embed, view=self)
            else:
                await ctx_or_interaction.response.send_message(embed=first_embed, view=self)
                self.message = await ctx_or_interaction.original_response()

        else:  # fallback (DMs, etc.)
            try:
                self.message = await ctx_or_interaction.send(embed=first_embed, view=self)
            except Exception:
                pass

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Only allow the original author to press buttons."""
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(
                "⛔ Only the command author can use these buttons!", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="◀️ Prev", style=discord.ButtonStyle.primary)
    async def prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = (self.index - 1) % len(self.embeds)
        await interaction.response.edit_message(embed=self.embeds[self.index], view=self)

    @discord.ui.button(label="▶️ Next", style=discord.ButtonStyle.primary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = (self.index + 1) % len(self.embeds)
        await interaction.response.edit_message(embed=self.embeds[self.index], view=self)

    async def on_timeout(self):
        """Disable buttons when paginator times out."""
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass
# ─── ADMIN & JSON Utils ────────────────────────────
ADMIN_IDS = set(int(uid.strip()) for uid in os.getenv("ADMIN_IDS", "").split(",") if uid.strip())

def is_admin(user: Union[discord.User, discord.Member]) -> bool:
    if user.id in ADMIN_IDS:
        return True
    if isinstance(user, discord.Member):
        return user.guild_permissions.administrator
    return False

def dm_link(thread: Union[discord.Thread, discord.Message]) -> str:
    """Returns a clickable jump link to a thread or message."""
    if isinstance(thread, (discord.Thread, discord.Message)):
        return thread.jump_url
    return "Link unavailable"

def load_json_file(filename: str, default: Any):
    """Load a JSON file safely."""
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


LEADERBOARD_LOCK = asyncio.Lock()
channel_id = int(os.getenv("LEADERBOARD_CHANNEL_ID", 0))
async def award_points(
    bot: discord.Client,
    user: discord.Member,
    points: int = 1,
    notify_channel=None,
    dm=False
):
    if channel_id is None:
        print("[DEBUG] No leaderboard channel provided.")
        return

    # Determine the sign for messages
    sign = "+" if points >= 0 else "-"
    abs_points = abs(points)

    # Fetch leaderboard channel
    channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
    if not channel:
        print(f"[DEBUG] Leaderboard channel {channel_id} not found.")
        return

    async with LEADERBOARD_LOCK:
        # Get last message
        try:
            msg = [m async for m in channel.history(limit=1, oldest_first=False)][0]
        except IndexError:
            # No leaderboard exists yet
            msg = await channel.send(f"{user.display_name} - {user.id} - {points}")
            if notify_channel:
                action = "earned" if points >= 0 else "lost"
                await notify_channel.send(f"💎 {user.mention} {action} **{abs_points:,} gems**!")
            return

        lines = msg.content.splitlines()
        user_found = False
        new_lines = []

        for line in lines:
            parts = [p.strip() for p in line.split("-")]
            if len(parts) != 3:
                new_lines.append(line)
                continue

            name, uid_str, pts_str = parts
            try:
                uid = int(uid_str)
                pts = int(pts_str)
            except:
                new_lines.append(line)
                continue

            if uid == user.id:
                pts += points
                user_found = True
                new_lines.append(f"{name} - {uid} - {pts}")
            else:
                new_lines.append(line)

        # If user not found, add them
        if not user_found:
            new_lines.append(f"{user.display_name} - {user.id} - {points}")

        # Edit the last leaderboard message
        await msg.edit(content="\n".join(new_lines))

        # Notification message
        action = "earned" if points >= 0 else "lost"
        message = f"💎 {user.display_name} {action} {sign}{abs_points:,} gems!"

        if dm:
            try:
                await user.send(message)
            except discord.Forbidden:
                # User has DMs closed
                if notify_channel:
                    await notify_channel.send(message)
        else:
            if notify_channel:
                await notify_channel.send(message)
            elif channel_id:
                channel = bot.get_channel(channel_id)
                if channel:
                    await channel.send(message)


# ---------------- DAILY QUEST ----------------
# Admin channel ID for daily quests
DAILY_QUEST_CHANNEL_ID = int(os.getenv("DAILY_QUEST_CHANNEL_ID", 0))

# All daily quest IDs in order
DAILY_QUEST_IDS = ["a", "b", "c", "d"]
async def update_daily_quest(bot: commands.Bot, member: discord.Member, quest_id: str):
    channel = bot.get_channel(DAILY_QUEST_CHANNEL_ID)
    if not channel:
        return  # channel not found

    # Get the last message in the channel
    last_message = None
    async for msg in channel.history(limit=1):
        last_message = msg
        break

    if not last_message:
        return  # no messages, nothing to do

    lines = last_message.content.splitlines()
    updated_lines = []

    for line in lines:
        if str(member.id) in line:
            # Update quest_id from 0 → 1
            updated_line = line.replace(f"{quest_id}0", f"{quest_id}1")
            updated_lines.append(updated_line)
        else:
            updated_lines.append(line)

    # Only edit if a change was made
    if lines != updated_lines:
        await last_message.edit(content="\n".join(updated_lines))
