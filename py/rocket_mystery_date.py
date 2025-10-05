# mystery_date_cog.py
import asyncio
import random
import discord
from discord.ext import commands
from typing import Optional
import os
from helpers import award_points, ONGOING_SESSIONS


def has_any_role(member: discord.Member, role_names: set) -> bool:
    """Check if member has any of the specified roles."""
    return any(role.name in role_names for role in member.roles)


class StartButton(discord.ui.View):
    """Button for Caller 1 to start the Mystery Date conversation."""

    def __init__(self, other_channel: discord.TextChannel):
        super().__init__(timeout=None)
        self.other_channel = other_channel

    @discord.ui.button(label="Start", style=discord.ButtonStyle.success, emoji="💌")
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await self.other_channel.send("hi")
            await self.other_channel.send("💕 Your Mystery Date has started! Caller 1 just said hi!")
            await interaction.response.send_message("✅ You started the game with a 'hi'!", ephemeral=True)
            self.stop()
        except Exception as e:
            await interaction.response.send_message(f"❌ Couldn't send start message: {e}", ephemeral=True)


class MysteryDate(commands.Cog):
    """Mystery Date cog using ONGOING_SESSIONS to track active games."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active_games: dict[int, dict] = {}  # channel.id -> {"task": asyncio.Task, "last_message": discord.Message}
        self.settings: dict = {}
        self.settings_loaded = False

        # Role/channel IDs from environment
        self.catch_pokemen_id = int(os.getenv("CATCH_POKEMEN_ID", 0))
        self.catch_pokewomen_id = int(os.getenv("CATCH_POKEWOMEN_ID", 0))
        self.catch_all_id = int(os.getenv("CATCH_ALL_ID", 0))
        self.choose_roles_channel_id = int(os.getenv("CHOOSE_ROLES_CHANNEL_ID", 0))

    # ---------------- Load settings ----------------
    async def load_settings_from_admin(self, admin_channel: discord.TextChannel):
        """Load all game settings from the first message in the admin channel."""
        try:
            first_message = None
            async for msg in admin_channel.history(limit=1, oldest_first=True):
                first_message = msg
                break
            if not first_message:
                return False

            parsed = {}
            for line in first_message.content.splitlines():
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                parsed[key.strip()] = value.strip()

            self.settings = {
                "CHANNEL_1_ID": int(parsed.get("CHANNEL_1_ID", 0)),
                "CHANNEL_2_ID": int(parsed.get("CHANNEL_2_ID", 0)),
                "ALLOWED_USERS": int(parsed.get("ALLOWED_USERS", 1)),
                "REPLY_MINUTE": int(parsed.get("REPLY_MINUTE", 2)),
                "MYSTERY_CHANNEL_ID": int(parsed.get("MYSTERY_CHANNEL_ID", 0)),
                "PLAYER_LABELS": [v.strip() for v in parsed.get("PLAYER_LABELS", "Caller 1,Caller 2").split(",")],
                "TIMEOUT_REASON": parsed.get("TIMEOUT_REASON", "Time's up!"),
                "TIP_TEXT": parsed.get("TIP_TEXT", "Be kind!"),
                "SEND_CONFIRMATION_TEMPLATE": parsed.get(
                    "SEND_CONFIRMATION_TEMPLATE",
                    "✅ Your message has been sent to {target_name}: \"{content}\""
                ),
                "FOOTER_TEMPLATE": parsed.get(
                    "FOOTER_TEMPLATE",
                    "Tip: {tip} • Time left: {minutes:02d}:{seconds:02d}"
                ),
            }
            self.settings_loaded = True
            return True
        except Exception as e:
            print(f"Settings load failed: {e}")
            return False

    # ---------------- Helpers ----------------
    def channel_member_count(self, channel: discord.abc.GuildChannel) -> int:
        return len([m for m in getattr(channel, "members", []) if not m.bot])

    async def clear_channel_access(self, channel: discord.TextChannel):
        for m in channel.members:
            if not m.bot:
                try:
                    await channel.set_permissions(m, overwrite=None)
                except Exception:
                    pass

    async def end_game(self, channel_1: discord.TextChannel, channel_2: discord.TextChannel, reason: str):
        """End the game, reset session in ONGOING_SESSIONS, and award points."""
        guild = channel_1.guild
        ONGOING_SESSIONS["mystery_date"].pop(guild.id, None)

        # Load admin IDs once
        ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()}

        players = []
        for ch in (channel_1, channel_2):
            if not ch:
                continue
            members = [m for m in ch.members if not m.bot]
            players.extend(members)
            for m in members:
                try:
                    await ch.set_permissions(m, overwrite=None)
                except Exception:
                    pass
            try:
                await ch.send(f"🚨 Mystery Date ended: {reason}")
            except Exception:
                pass

        # 🧩 Award points (skip admins)
        for player in players:
            if player.id in ADMIN_IDS:
                print(f"[DEBUG] Skipping award for admin: {player}")
                continue
            try:
                await award_points(self.bot, player, 50, dm=True)
            except Exception as e:
                print(f"[DEBUG] Could not award points to {player}: {e}")

        # Cancel active countdown tasks
        for key in list(self.active_games.keys()):
            task = self.active_games[key].get("task")
            if task and not task.done():
                task.cancel()
            self.active_games.pop(key, None)

        # Flavor announcement
        mystery_channel = guild.get_channel(self.settings.get("MYSTERY_CHANNEL_ID", 0))
        if mystery_channel:
            messages = [
                f"🚨 A Mystery Date just ended: {reason}",
                "✨ Jessie whispers: another secret romance concluded! ✨",
                "😼 Meowth: That’s a wrap — Mystery Date closed! 💕",
                "🎭 James sighs: Another anonymous adventure ends! 🌟",
                "🌌 Wobbuffet: The curtain falls on this Mystery Date! ✨"
            ]
            await mystery_channel.send(random.choice(messages))

    # ---------------- Commands ----------------
    @commands.command(name="md")
    async def md_start(self, ctx: commands.Context, action: Optional[str] = None):
        guild = ctx.guild
        if not guild:
            return

        admin_channel_id = int(os.getenv("ADMIN_MYSTERY_CHANNEL_ID", 0))
        admin_channel = guild.get_channel(admin_channel_id)
        mystery_channel_id = int(os.getenv("MYSTERY_CHANNEL_ID", 0))

        if not admin_channel or not await self.load_settings_from_admin(admin_channel):
            return await ctx.send("❌ Settings not ready. Ask an admin.")

        if ctx.channel.id != mystery_channel_id:
            try:
                await ctx.author.send(
                    f"❌ You can only start a Mystery Date in {guild.get_channel(mystery_channel_id).mention}."
                )
            except:
                await ctx.send(f"❌ Use the correct Mystery Date channel.", delete_after=10)
            return

        if action != "start":
            return await ctx.send("❌ Wrong usage! Use `.md start` to begin.")

        if not has_any_role(ctx.author, {"Catching PokeMen", "Catching PokeWomen", "Catching 'em all"}):
            return await ctx.send(
                f"❌ Only contestants with Catching roles can join. Assign one in <#{self.choose_roles_channel_id}>."
            )

        if ONGOING_SESSIONS["mystery_date"].get(guild.id, False):
            return await ctx.send("⛔ A Mystery Date is already running — wait for it to finish!")

        # Prevent overlapping Talk to Stranger
        if ONGOING_SESSIONS["talk_to_stranger"].get(guild.id, False):
            return await ctx.send("⛔ Cannot start Mystery Date while Talk to Stranger is running!")

        ONGOING_SESSIONS["mystery_date"][guild.id] = True

        ch1 = guild.get_channel(self.settings["CHANNEL_1_ID"])
        ch2 = guild.get_channel(self.settings["CHANNEL_2_ID"])
        if not ch1 or not ch2:
            return await ctx.send("❌ Player channels misconfigured.")

        await self.clear_channel_access(ch1)
        await self.clear_channel_access(ch2)

        # Assign player to free channel
        if self.channel_member_count(ch1) < self.settings["ALLOWED_USERS"]:
            target_channel, player_label, other_label = ch1, self.settings["PLAYER_LABELS"][0], self.settings["PLAYER_LABELS"][1]
        elif self.channel_member_count(ch2) < self.settings["ALLOWED_USERS"]:
            target_channel, player_label, other_label = ch2, self.settings["PLAYER_LABELS"][1], self.settings["PLAYER_LABELS"][0]
        else:
            return await ctx.send("Both channels are occupied. Wait for current game to finish.")

        await target_channel.set_permissions(ctx.author, read_messages=True, send_messages=True)

        try:
            await ctx.author.send(f"💥 You joined Mystery Date! Go to {target_channel.mention}.")
        except Exception:
            await ctx.send(f"💥 {ctx.author.mention}, you joined **{player_label}**.")

        # Flavor messages
        rocket_mention = guild.get_channel(self.settings.get("MYSTERY_CHANNEL_ID", 0)).mention
        await ctx.send(random.choice([
            f"🎭 **Caller 1** is lurking… @everyone join as Caller 2 in {rocket_mention}!",
            f"💘 Caller 1 waits… @everyone click **Mystery Date** in {rocket_mention} to join as Caller 2!",
            f"🔥 Tension rises! Caller 1 is ready… @everyone step in as Caller 2 in {rocket_mention}!",
        ]))

        welcome = (
            f"💥 Welcome, {player_label}!\n"
            f"You are {player_label}, your date is {other_label}.\n"
            f"👉 Click **Start 💌** to send your first message!\n"
            f"⏱ {other_label} has {self.settings['REPLY_MINUTE']} minute(s) to reply."
        )

        other_channel = ch2 if target_channel.id == ch1.id else ch1
        view = StartButton(other_channel)
        sent = await target_channel.send(welcome, view=view)

        if player_label == self.settings["PLAYER_LABELS"][0]:
            task = asyncio.create_task(
                self.live_countdown(sent, self.settings["REPLY_MINUTE"], other_label, guild.id)
            )
            self.active_games[target_channel.id] = {"task": task, "last_message": sent}

    # ---------------- Listeners ----------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not self.settings_loaded:
            return
        if message.channel.id not in {self.settings["CHANNEL_1_ID"], self.settings["CHANNEL_2_ID"]}:
            return

        guild_id = message.guild.id
        if not ONGOING_SESSIONS["mystery_date"].get(guild_id, False):
            return

        if message.channel.id == self.settings["CHANNEL_1_ID"]:
            target_channel = self.bot.get_channel(self.settings["CHANNEL_2_ID"])
            masked_name, target_name = self.settings["PLAYER_LABELS"][0], self.settings["PLAYER_LABELS"][1]
        else:
            target_channel = self.bot.get_channel(self.settings["CHANNEL_1_ID"])
            masked_name, target_name = self.settings["PLAYER_LABELS"][1], self.settings["PLAYER_LABELS"][0]

        if not target_channel:
            return

        try:
            await message.delete()
        except Exception:
            pass

        confirmation_text = self.settings["SEND_CONFIRMATION_TEMPLATE"].format(
            target_name=target_name, content=message.content
        )
        await message.channel.send(confirmation_text)

        embed = discord.Embed(description=message.content, color=discord.Color.green())
        embed.set_author(name=masked_name)
        minutes, seconds = divmod(self.settings["REPLY_MINUTE"] * 60, 60)
        embed.set_footer(text=self.settings["FOOTER_TEMPLATE"].format(
            tip=self.settings["TIP_TEXT"], minutes=minutes, seconds=seconds
        ))
        sent_embed = await target_channel.send(embed=embed)

        prev = self.active_games.get(message.channel.id)
        if prev and prev.get("task") and not prev["task"].done():
            prev["task"].cancel()

        task = asyncio.create_task(self.turn_countdown(message.channel, sent_embed))
        self.active_games[message.channel.id] = {"task": task, "last_message": sent_embed}

    async def turn_countdown(self, channel: discord.TextChannel, sent: discord.Message):
        total_seconds = self.settings["REPLY_MINUTE"] * 60
        try:
            while total_seconds > 0:
                m, s = divmod(total_seconds, 60)
                if sent.embeds:
                    embed = sent.embeds[0]
                    embed.set_footer(text=self.settings["FOOTER_TEMPLATE"].format(
                        tip=self.settings["TIP_TEXT"], minutes=m, seconds=s
                    ))
                    await sent.edit(embed=embed)
                await asyncio.sleep(1)
                total_seconds -= 1

            await self.end_game(
                self.bot.get_channel(self.settings["CHANNEL_1_ID"]),
                self.bot.get_channel(self.settings["CHANNEL_2_ID"]),
                reason=self.settings["TIMEOUT_REASON"]
            )
        except asyncio.CancelledError:
            return

    async def live_countdown(self, sent: discord.Message, minutes: int, other_label: str, guild_id: int):
        total_seconds = minutes * 60
        try:
            while total_seconds > 0:
                m, s = divmod(total_seconds, 60)
                if sent.embeds:
                    embed = sent.embeds[0]
                    embed.set_footer(text=self.settings["FOOTER_TEMPLATE"].format(
                        tip=self.settings["TIP_TEXT"], minutes=m, seconds=s
                    ))
                    await sent.edit(embed=embed)
                await asyncio.sleep(1)
                total_seconds -= 1

            await self.end_game(
                self.bot.get_channel(self.settings["CHANNEL_1_ID"]),
                self.bot.get_channel(self.settings["CHANNEL_2_ID"]),
                reason=self.settings["TIMEOUT_REASON"]
            )
        except asyncio.CancelledError:
            return


async def setup(bot: commands.Bot):
    await bot.add_cog(MysteryDate(bot))
