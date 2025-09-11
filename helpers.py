# =============================
# helpers.py (refactored)
# =============================
import os
import json
import sqlite3
from datetime import datetime, timezone
from typing import List, Optional, Union, Any, Dict, Tuple

import discord
from discord.ext import commands

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
def is_pokecandidate(member: discord.Member) -> bool:
    """Return True if member has either PokeCandidates or TEAM ROCKET roles."""
    role_names = {r.name.lower() for r in member.roles}
    return ("pokecandidates" in role_names) or ("team rocket" in role_names)


def get_gender_emoji(member: discord.Member) -> str:
    role_names = {r.name.lower() for r in member.roles}
    if "rocket pokewoman ♀️" in role_names:
        return "♀️"
    if "rocket pokeman ♂️" in role_names:
        return "♂️"
    if "rocket pokepal ⚧" in role_names:
        return "⚧"
    return "❓"


def get_guild_contestants(guild: discord.Guild) -> List[discord.Member]:
    """Return all members in the guild who have either PokeCandidates or TEAM ROCKET roles."""
    poke_role = discord.utils.get(guild.roles, name="PokeCandidates")
    rocket_role = discord.utils.get(guild.roles, name="TEAM ROCKET")
    if not poke_role and not rocket_role:
        return []
    return [
        m for m in guild.members
        if not m.bot and (poke_role in m.roles or rocket_role in m.roles)
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
    """Paginator for embed pages."""
    def __init__(self, embeds: List[discord.Embed]):
        super().__init__(timeout=60)
        self.embeds = embeds
        self.index = 0

    async def start(self, ctx_or_interaction):
        await safe_send(ctx_or_interaction, embed=self.embeds[self.index], view=self)

    @discord.ui.button(label="◀️ Prev", style=discord.ButtonStyle.primary)
    async def prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = (self.index - 1) % len(self.embeds)
        await interaction.response.edit_message(embed=self.embeds[self.index], view=self)

    @discord.ui.button(label="▶️ Next", style=discord.ButtonStyle.primary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = (self.index + 1) % len(self.embeds)
        await interaction.response.edit_message(embed=self.embeds[self.index], view=self)


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




