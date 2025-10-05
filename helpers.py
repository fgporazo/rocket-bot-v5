# =============================
# helpers.py (refactored + fixed for Railway persistence)
# =============================
import os
import asyncio
import json
import sqlite3
from datetime import datetime, timezone
from typing import List, Optional, Union, Any, Dict, Tuple

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

# ─── Database Path ─────────────────────────────
# Ensure persistent path on Railway (Volume mount at /data)
PERSIST_DIR = "/data"
DB_PATH = os.path.join(PERSIST_DIR, "rocket.db")

# Fallback for local testing (if /data does not exist)
if not os.path.exists(PERSIST_DIR):
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    DB_PATH = os.path.join(BASE_DIR, "rocket.db")

print(f"[INIT] Using database path: {DB_PATH}")

# ─── Daily Limits ─────────────────────────────
ADMIN_DATE_LIMIT_PER_DAY = 5
USER_DATE_LIMIT_PER_DAY = 3

# ─── DB Init ─────────────────────────────
def init_db():
    """Initialize SQLite database and ensure folder exists."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
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
    print(f"[INIT] Database initialized successfully at {DB_PATH}")


# ─── Role-based Helpers ─────────────────────────────
async def reset_heartthrob_role(guild: discord.Guild, role_name: str, top_member_id: int) -> Optional[discord.Role]:
    """Remove the Heartthrob role from everyone except the top scorer."""
    role = discord.utils.get(guild.roles, name=role_name)
    if not role:
        return None

    for member in guild.members:
        if role in member.roles and member.id != top_member_id:
            try:
                await member.remove_roles(role, reason="Reset Heartthrob role")
            except Exception as e:
                print(f"[ERROR] Cannot remove role from {member}: {e}")
    return role


def is_edate_gamer(member: discord.Member) -> bool:
    """Return True if member has any Poke-related or Team Rocket role."""
    role_names = {r.name.lower() for r in member.roles}
    allowed_roles = {"team rocket", "catching pokemen", "catching pokewomen", "catching 'em all"}
    return bool(role_names & allowed_roles)


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
    """Return all non-bot members in the guild who have at least one catching role."""
    catch_role_names = {"Catching PokeMen", "Catching PokeWomen", "Catching 'em all", "Team Rocket"}
    catch_roles = {role for role in guild.roles if role.name in catch_role_names}

    if not catch_roles:
        return []

    return [m for m in guild.members if not m.bot and any(r in m.roles for r in catch_roles)]


# ─── Time helpers ─────────────────────────────
def utc_today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── Database Record Helpers ─────────────────────────────
def count_sent_today(guild_id: int, sender_id: int) -> int:
    today = utc_today_str()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT COUNT(*) FROM e_date_records WHERE guild_id=? AND e_date_sender_id=? AND date=?",
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
    c.execute("UPDATE e_date_records SET status=?, reason=? WHERE id=?", (status, reason, record_id))
    conn.commit()
    conn.close()


def fetch_incoming_history(guild_id: int, receiver_id: int) -> List[Tuple[str, int, str, str]]:
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
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id FROM e_date_records WHERE guild_id=? AND status='yes'", (guild.id,))
    recv_rows = [r[0] for r in c.fetchall()]
    c.execute("SELECT e_date_sender_id FROM e_date_records WHERE guild_id=? AND status='yes'", (guild.id,))
    send_rows = [r[0] for r in c.fetchall()]
    conn.close()

    points: Dict[int, int] = {}
    for uid in recv_rows + send_rows:
        points[uid] = points.get(uid, 0) + 1

    valid_ids = {m.id for m in get_guild_contestants(guild)}
    return {uid: pts for uid, pts in points.items() if uid in valid_ids}


# ─── Messaging Utilities ─────────────────────────────
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


# ─── Pagination Classes (Unchanged) ─────────────────────────────
# [You can keep your existing TextPaginator and EmbedPaginator unchanged here — no need to alter them]


# ─── ADMIN & JSON Utils ─────────────────────────────
ADMIN_IDS = {int(uid.strip()) for uid in os.getenv("ADMIN_IDS", "").split(",") if uid.strip()}


def is_admin(user: Union[discord.User, discord.Member]) -> bool:
    if user.id in ADMIN_IDS:
        return True
    if isinstance(user, discord.Member):
        return user.guild_permissions.administrator
    return False


def dm_link(thread: Union[discord.Thread, discord.Message]) -> str:
    return thread.jump_url if isinstance(thread, (discord.Thread, discord.Message)) else "Link unavailable"


def load_json_file(filename: str, default: Any):
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


# ─── Leaderboard & Daily Quest (Unchanged) ─────────────────────────────
# [Keep your existing award_points and update_daily_quest code here — they’re fine]


# ─── ONGOING SESSION TRACKERS ─────────────────────────────
ONGOING_SESSIONS = {
    "mystery_date": {},
    "talk_to_stranger": {}
}
