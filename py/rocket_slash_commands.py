import discord
import random
import json
import os
import time
from discord import app_commands
from discord.ext import commands, tasks
from discord.ui import View
from helpers import is_admin

# ----------------- Button Styles ------------
STYLE_MAP = {
    "success": discord.ButtonStyle.success,
    "danger": discord.ButtonStyle.danger,
    "primary": discord.ButtonStyle.primary
}

# ----------------- Cooldown -----------------
CLICK_TRACKER: dict[int, dict[str, list[float]]] = {}

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

        # ----------------- Send to DM if required -----------------
        if self.dm_notify:
            try:
                await interaction.user.send(f"💌 Executed command: `{self.command}`")
            except discord.Forbidden:
                await interaction.followup.send("🚀 I couldn't DM you, enable DMs.", ephemeral=True)

        # ----------------- Send command to all channels -----------------
        if not interaction.guild:
            await interaction.followup.send("❌ Cannot use this command in DMs for channels.", ephemeral=True)
            return

        sent_channels = []
        for cid in self.channel_ids:
            target_channel = interaction.guild.get_channel(int(cid))
            if target_channel:
                fake_message = await target_channel.send(f"💥 `{self.command}` triggered by {interaction.user.mention}")
                fake_message.author = interaction.user
                fake_message.content = self.command
                ctx = await self.bot.get_context(fake_message, cls=commands.Context)
                if ctx.command:
                    await self.bot.invoke(ctx)
                await fake_message.delete()
                sent_channels.append(target_channel.name)

        if sent_channels:
            # Create clickable channel mentions
            channel_mentions = []
            for cid in self.channel_ids:
                channel = interaction.guild.get_channel(int(cid))
                if channel:
                    channel_mentions.append(channel.mention)
            if channel_mentions:
                await interaction.followup.send(f"✅ Go to: {', '.join(channel_mentions)}", ephemeral=True)
            else:
                await interaction.followup.send("⚠️ No valid channels found to send this command.", ephemeral=True)


# ----------------- RocketListView -----------------
class RocketListView(View):
    def __init__(self, bot: commands.Bot, section: dict):
        super().__init__(timeout=None)
        self.bot = bot

        # Get the section-level button style
        section_style_str = str(section.get("button_style", "success")).lower()
        section_style = STYLE_MAP.get(section_style_str, discord.ButtonStyle.success)

        # Add all buttons in this section using the section's style
        for button_data in section.get("buttons", []):
            self.add_item(
                CommandButton(
                    label=button_data.get("label", "Unnamed"),
                    command=button_data.get("command", ""),
                    style=section_style,
                    bot=bot,
                    channel_ids=button_data.get("channel_ids", []),
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

    # ---------- Rocket Escape Room ----------
    @app_commands.command(name="rocket-escape-room", description="Show Rocket Escape Room Menu (Admins only).")
    async def rocket_escape_room(self, interaction: discord.Interaction):
        if not is_admin(interaction.user):
            return await interaction.response.send_message(
                "🚫 Only admins can use this command.", ephemeral=True
            )

        # ----------------- Embed Title & Description -----------------
        channel_name_or_id = os.getenv("ADMIN_ESCAPE_STORY_CHANNEL_ID")
        escape_channel = None
        if channel_name_or_id and interaction.guild:
            escape_channel = (
                interaction.guild.get_channel(int(channel_name_or_id)) if channel_name_or_id.isdigit()
                else discord.utils.get(interaction.guild.text_channels, name=channel_name_or_id)
            )

        title = "🚪 Team Rocket Escape Room"
        description = "Join the madness and help Team Rocket!"

        if escape_channel:
            last_message = None
            async for msg in escape_channel.history(limit=50):
                if msg.content.strip():
                    last_message = msg
                    break
            if last_message:
                lines = last_message.content.split("\n")
                title = lines[0] if lines else title
                description = "\n".join(lines[1:]) if len(lines) > 1 else description

        embed = discord.Embed(
            title=title,
            description=description,
            color=discord.Color.red()
        )

        class EscapeRoomButton(discord.ui.Button):
            def __init__(self, bot: commands.Bot):
                super().__init__(label="Join Escape Room", style=discord.ButtonStyle.success)
                self.bot = bot

            async def callback(self, interaction: discord.Interaction):
                guild = interaction.guild
                if guild is None:
                    return await interaction.response.send_message(
                        "❌ This button can only be used in a server.", ephemeral=True
                    )

                escape_channel = discord.utils.get(guild.channels, name="🚪🔐-escape-room")
                if not escape_channel:
                    return await interaction.response.send_message(
                        "❌ No escape room channel found! Please ask an admin to create one.",
                        ephemeral=True
                    )

                active_thread = None
                if isinstance(escape_channel, discord.TextChannel):
                    for thread in escape_channel.threads:
                        if not thread.archived:
                            active_thread = thread
                            break

                if active_thread:
                    await interaction.response.send_message(
                        f"🚪 The escape room is ready in {active_thread.mention}! ✅ Head there and type **.er join** or **.er start**.",
                        ephemeral=True)
                else:
                    await interaction.response.send_message(
                        "⚠️ No active escape room found. Return to Rocket Bot channel and click Escape Room to start a new game!",
                        ephemeral=True
                    )

        view = discord.ui.View(timeout=None)
        view.add_item(EscapeRoomButton(self.bot))
        await interaction.response.send_message(embed=embed, view=view)
    
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


# ----------------- Cog Setup -----------------
async def setup(bot: commands.Bot):
    await bot.add_cog(RocketSlash(bot))
