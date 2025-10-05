import discord
import random
import json
import os
import time
from discord import app_commands
from discord.ext import commands
from discord.ui import View
from helpers import is_admin, award_points
import re
# ----------------- Button Styles ------------
STYLE_MAP = {
    "success": discord.ButtonStyle.success,
    "danger": discord.ButtonStyle.danger,
    "primary": discord.ButtonStyle.primary
}

# ----------------- Cooldown -----------------
CLICK_TRACKER: dict[int, dict[str, list[float]]] = {}
LEADERBOARD_CHANNEL_ID = int(os.getenv("LEADERBOARD_CHANNEL_ID", 0))
# ----------------- Command Button -----------------
class CommandButton(discord.ui.Button):
    def __init__(self, label: str, command: str, style: discord.ButtonStyle, bot: commands.Bot,
                 channel_ids: list[str] | None = None, dm_notify: bool = False):
        super().__init__(label=label, style=style, custom_id=f"btn_{label}")
        self.command = command
        self.bot = bot
        self.channel_ids = channel_ids or []
        self.dm_notify = dm_notify
        self.cooldown_seconds = 300  # 5 minutes

    async def callback(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        now = time.time()

        # ----------------- Cooldown -----------------
        if user_id not in CLICK_TRACKER:
            CLICK_TRACKER[user_id] = {}
        custom_id = self.custom_id or f"btn_{self.label}"
        if custom_id not in CLICK_TRACKER[user_id]:
            CLICK_TRACKER[user_id][custom_id] = []
        timestamps = [t for t in CLICK_TRACKER[user_id][custom_id] if now - t < self.cooldown_seconds]
        CLICK_TRACKER[user_id][custom_id] = timestamps
        if len(timestamps) >= 3:
            remaining = int(self.cooldown_seconds - (now - timestamps[0]))
            minutes, seconds = divmod(remaining, 60)
            lines = [
                f"😼 Meowth: Nyehehe! Slow down, twerp! Wait {minutes}m {seconds}s!",
                f"💋 Jessie: Patience, twerp! Give it {minutes}m {seconds}s!",
                f"🎩 James: Oh dear… wait {minutes}m {seconds}s before clicking again!"
            ]
            await interaction.response.send_message(random.choice(lines), ephemeral=True)
            return
        timestamps.append(now)
        CLICK_TRACKER[user_id][custom_id] = timestamps

        # ----------------- DM-only -----------------
        if not self.command.strip():
            try:
                await interaction.user.send("🚀 Team Rocket says Hi! Send feedback with **.tr feedback <message>**.")
                await interaction.response.send_message("✅ Check your DMs!", ephemeral=True)
            except discord.Forbidden:
                await interaction.response.send_message("🚀 I couldn't DM you, enable DMs.", ephemeral=True)
            return

        # ----------------- Defer -----------------
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.InteractionResponded:
            pass

        if not interaction.guild:
            await interaction.followup.send("❌ Cannot use this command in DMs.", ephemeral=True)
            return

        # ----------------- Prepare run channels -----------------
        run_channels = []
        for cid in self.channel_ids:
            ch = interaction.guild.get_channel(int(cid))
            if ch:
                run_channels.append(ch)

        # Fallback if empty
        if not run_channels and interaction.channel:
            run_channels.append(interaction.channel)

        if not run_channels:
            await interaction.followup.send("❌ No valid channels found to execute command.", ephemeral=True)
            return

        # ----------------- Execute command in the first channel -----------------
        target_channel = run_channels[0]
        rocket_click_lines = [
            "💋 Jessie: `{label}` clicked—check your DMs!",
            "🎩 James: `{label}` clicked—Team Rocket’s watching!",
            "😼 Meowth: `{label}` clicked? Bold move, twerp!"
        ]
        fake_message = await target_channel.send(random.choice(rocket_click_lines).format(label=self.label))
        fake_message.author = interaction.user
        fake_message.content = self.command
        ctx = await self.bot.get_context(fake_message, cls=commands.Context)
        if ctx.command:
            await self.bot.invoke(ctx)
        #await fake_message.delete()

        # ----------------- Notify user with clickable links -----------------
        links = [f"[**{ch.name}**]({ch.jump_url})" for ch in run_channels]
        await interaction.followup.send(
            f"Check your DMs!",
            ephemeral=True
        )


# ----------------- RocketListView -----------------
class RocketListView(View):
    def __init__(self, bot: commands.Bot, section: dict):
        super().__init__(timeout=None)
        self.bot = bot

        section_style_str = str(section.get("button_style", "success")).lower()
        section_style = STYLE_MAP.get(section_style_str, discord.ButtonStyle.success)

        for button_data in section.get("buttons", []):
            self.add_item(
                CommandButton(
                    label=button_data.get("label", "Unnamed"),
                    command=button_data.get("command", ""),
                    style=section_style,
                    bot=bot,
                    channel_ids=button_data.get("channel_ids"),
                    dm_notify=button_data.get("DM", False)
                )
            )


# ----------------- RocketSlash Cog -----------------
class RocketSlash(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ----------------- Fetch Latest JSON -----------------
    async def fetch_latest_json(self):
        channel_id = os.getenv("ADMIN_ROCKET_LIST_CHANNEL_ID")
        if not channel_id or not channel_id.isdigit():
            return None
        channel = self.bot.get_channel(int(channel_id))
        if not channel:
            return None
        async for msg in channel.history(limit=50):
            if msg.attachments:
                for att in msg.attachments:
                    if att.filename.endswith(".json"):
                        data_bytes = await att.read()
                        try:
                            return json.loads(data_bytes.decode("utf-8"))
                        except Exception:
                            continue
        return None

    # ----------------- Rocket List -----------------
    @app_commands.command(name="rocket-list", description="Show Rocket Bot menu (Admins only).")
    async def rocket_list(self, interaction: discord.Interaction):
        if not is_admin(interaction.user):
            return await interaction.response.send_message("🚫 Only admins can use this command.", ephemeral=True)

        data = await self.fetch_latest_json()
        if not data:
            return await interaction.response.send_message("⚠️ Could not find any JSON file in the admin channel.", ephemeral=True)

        sections = data.get("sections", [])
        for idx, section in enumerate(sections):
            embed = discord.Embed(
                title=section.get("title", "🚀 Rocket Bot"),
                description=section.get("description", ""),
                color=discord.Color.blurple()
            )
            view = RocketListView(self.bot, section)
            if idx == 0:
                await interaction.response.send_message(embed=embed, view=view)
            else:
                await interaction.followup.send(embed=embed, view=view)

    # ----------------- Rocket Members -----------------
    @app_commands.command(name="rocket-members", description="👥 View Team Rocket Admin")
    async def rocket_members(self, interaction: discord.Interaction):
        embed = discord.Embed(title="Team Rocket Admin",
                              description="Meet the chaos crew behind the scenes! 💥",
                              color=0xFFFACD)
        embed.add_field(name="1️⃣ Jessie (Cin)", value="💄 Queen of Chaotic Capers", inline=False)
        embed.add_field(name="2️⃣ James (Layli)", value="🌻 Chaos Catalyst of Digital", inline=False)
        embed.add_field(name="3️⃣ Meowth (Joa)", value="😼 Official Translator & Mischief Manager", inline=False)
        await interaction.response.send_message(embed=embed)

    # ----------------- Rocket Gems -----------------
    @app_commands.command(name="rocket-gems", description="Award or remove gems from a user (Admin only).")
    @app_commands.describe(
        member="The user to award or deduct gems from",
        gems="Number of gems (positive to add, negative to subtract)"
    )
    async def rocket_gems(self, interaction: discord.Interaction, member: discord.Member, gems: int):
        if not is_admin(interaction.user):
            return await interaction.response.send_message("🚫 Only admins can use this command.", ephemeral=True)

        if gems == 0:
            return await interaction.response.send_message("⚠️ Gems cannot be 0.", ephemeral=True)

        await award_points(self.bot, member, gems, notify_channel=interaction.channel)

        action = "rewarded to" if gems > 0 else "deducted from"
        await interaction.response.send_message(
            f"✅ {abs(gems):,} gems {action} {member.mention}!",
            ephemeral=False
        )

    # ----------------- Rocket Elites -----------------
    @app_commands.command(
        name="rocket-elites",
        description="Announce the top 10 E-Games scorers 🚀"
    )
    async def rocket_elites(self, interaction: discord.Interaction):
        try:
            # Make it a public announcement
            await interaction.response.defer(ephemeral=False)

            channel = self.bot.get_channel(LEADERBOARD_CHANNEL_ID)
            if not channel:
                return await interaction.followup.send("⚠️ Leaderboard channel not found.")

            # --- Fetch latest message ---
            msg = None
            async for m in channel.history(limit=5, oldest_first=False):
                if m.content:
                    msg = m
                    break

            if not msg:
                return await interaction.followup.send("⚠️ No leaderboard message found.")

            # --- Parse leaderboard ---
            leaderboard = []
            for line in msg.content.splitlines():
                parts = [p.strip() for p in line.split("-")]
                if len(parts) < 3:
                    continue
                name_str, uid_str, points_str = parts[-3], parts[-2], parts[-1]
                try:
                    uid = int(re.sub(r"\D", "", uid_str))
                    points = int(re.sub(r"\D", "", points_str))
                except ValueError:
                    continue
                leaderboard.append((name_str, uid, points))

            if not leaderboard:
                return await interaction.followup.send("⚠️ Leaderboard is empty or malformed.")

            # --- Sort by points descending and keep top 10 ---
            leaderboard.sort(key=lambda x: x[2], reverse=True)
            leaderboard = leaderboard[:10]

            guild = interaction.guild
            lines = []

            # Add title
            lines.append("# 🎖️ TOP 🔟 ROCKET ELITES 🎖️\n")

            for idx, (name, uid, points) in enumerate(leaderboard):
                try:
                    member = guild.get_member(uid) if guild else None
                    mention = member.mention if member else name
                except Exception:
                    mention = name

                medal = ["🥇", "🥈", "🥉"][idx] if idx < 3 else "🏅"
                number_emoji = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"][idx]

                # Add ## only to top 1
                prefix = "## " if idx == 0 else ""
                lines.append(f"{prefix}{number_emoji}  {medal} {mention} — 💎 {points}")

            final_message = "\n".join(lines)
            await interaction.followup.send(final_message)

        except Exception as e:
            print("🚨 Rocket-Elites Error:", e)
            await interaction.followup.send(f"⚠️ An error occurred:\n```{e}```")


# ----------------- Cog Setup -----------------
async def setup(bot: commands.Bot):
    await bot.add_cog(RocketSlash(bot))
