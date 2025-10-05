# rocket_talk.py
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
    """Button for Caller 1 to start the Talk to Stranger conversation."""

    def __init__(self, other_channel: discord.TextChannel):
        super().__init__(timeout=None)
        self.other_channel = other_channel

    @discord.ui.button(label="Start", style=discord.ButtonStyle.success, emoji="💬")
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await self.other_channel.send("hi")
            await self.other_channel.send("💬 Your Talk to Stranger session has started! Caller 1 just said hi!")
            await interaction.response.send_message(
                f"✅ You started the game with a 'hi'! Wait for other secret caller's reply.",
                ephemeral=True
            )
            self.stop()
        except Exception as e:
            await interaction.response.send_message(f"❌ Couldn't send start message: {e}", ephemeral=True)


class TalkToStranger(commands.Cog):
    """Talk to Stranger cog with masked relay, countdowns, and anonymous Team Rocket messages."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active_games: dict[int, dict] = {}   # channel.id -> {"task": asyncio.Task, "last_message": discord.Message}
        self.settings: dict = {}
        self.settings_loaded = False
        self.ongoing_sessions: dict[int, bool] = {}  # guild.id -> True/False

        # Role/channel IDs (from env)
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
        """Count human members in a channel (ignores bots)."""
        return len([m for m in getattr(channel, "members", []) if not m.bot])

    async def clear_channel_access(self, channel: discord.TextChannel):
        """Reset per-member overwrites (fresh for new session)."""
        for m in channel.members:
            if not m.bot:
                try:
                    await channel.set_permissions(m, overwrite=None)
                except Exception:
                    pass

    async def end_game(self, channel_1: discord.TextChannel, channel_2: discord.TextChannel, reason: str):
        """End the session, reset state, announce anonymously, and award gems to both players."""
        if not channel_1 or not channel_2:
            return

        guild = channel_1.guild
        guild_id = guild.id

        # --- Reset in-memory and global session states ---
        self.ongoing_sessions.pop(guild_id, None)
        ONGOING_SESSIONS.get("talk_to_stranger", {}).pop(guild_id, None)
        if guild_id in getattr(self, "cooldowns", {}):
            self.cooldowns.pop(guild_id, None)  # ✅ Reset cooldown state after restart or end

        # --- Gather non-bot players and remove permissions ---
        players = []
        for ch in (channel_1, channel_2):
            members = [m for m in ch.members if not m.bot]
            players.extend(members)
            for m in members:
                try:
                    await ch.set_permissions(m, overwrite=None)
                except Exception:
                    pass
            try:
                await ch.send(f"🚨 Talk To Stranger session ended: {reason}")
            except Exception:
                pass

        # --- Award gems to both players (ignore if failed) ---
        for player in players:
            try:
                await award_points(self.bot, player, 50, dm=True)
            except Exception as e:
                print(f"[DEBUG] Could not award points to {player}: {e}")

        # --- Cancel countdown timers or leftover async tasks ---
        for key in list(self.active_games.keys()):
            try:
                task = self.active_games[key].get("task")
                if task and not task.done():
                    task.cancel()
            except Exception:
                pass
            self.active_games.pop(key, None)

        # --- Post a flavor message in the main talk channel ---
        talk_channel = guild.get_channel(self.settings.get("MYSTERY_CHANNEL_ID", 0))
        if talk_channel:
            messages = [
                f"🚨 A Talk to Stranger session just ended: {reason}",
                "✨ Jessie whispers: another secret chat concluded! Thanks for playing! ✨",
                "😼 Meowth: That’s a wrap — Talk to Stranger room closed! 💕 Hope you enjoyed it!",
                "🎭 James sighs: Another anonymous chat ends! 🌟 Until the next session… stay mysterious!",
                "🌌 Wobbuffet: Curtain falls on this Talk to Stranger session! Hope you had fun! ✨"
            ]
            try:
                await talk_channel.send(random.choice(messages))
            except Exception as e:
                print(f"[DEBUG] Could not send flavor message: {e}")

        print(f"[DEBUG] Session cleanup completed for guild {guild_id}")

    # ---------------- Commands ----------------
    @commands.command(name="tts")
    async def tts_start(self, ctx: commands.Context, action: Optional[str] = None):
        guild = ctx.guild
        if not guild:
            return

        admin_channel_id = int(os.getenv("ADMIN_MYSTERY_CHANNEL_ID", 0))
        admin_channel = guild.get_channel(admin_channel_id)
        talk_channel_id = int(os.getenv("MYSTERY_CHANNEL_ID", 0))
        if not admin_channel or not await self.load_settings_from_admin(admin_channel):
            return await ctx.send("❌ Settings not ready. Ask an admin.")

        chosen_channel = guild.get_channel(self.settings.get("MYSTERY_CHANNEL_ID", 0))
        if ctx.channel.id != talk_channel_id:
            try:
                await ctx.author.send(
                    f"❌ You can only start Talk to Stranger in {chosen_channel.mention}."
                )
            except:
                await ctx.send(f"❌ You must use this command in {chosen_channel.mention}.", delete_after=10)
            return

        if action != "start":
            return await ctx.send("❌ Wrong usage! Use `.tts start` to begin.")

        # Check Mystery Date first
        if ONGOING_SESSIONS["mystery_date"].get(guild.id, False):
            return await ctx.send("⛔ Cannot start Talk to Stranger while Mystery Date is running!")

        # Check Talk to Stranger session
        if self.ongoing_sessions.get(guild.id, False) or ONGOING_SESSIONS["talk_to_stranger"].get(guild.id, False):
            return await ctx.send("⛔ A Talk to Stranger session is already running — wait for it to finish!")

        # Mark session active
        self.ongoing_sessions[guild.id] = True
        ONGOING_SESSIONS["talk_to_stranger"][guild.id] = True

        # Assign channels
        ch1 = guild.get_channel(self.settings["CHANNEL_1_ID"])
        ch2 = guild.get_channel(self.settings["CHANNEL_2_ID"])
        if not ch1 or not ch2:
            return await ctx.send("❌ Player channels misconfigured.")

        await self.clear_channel_access(ch1)
        await self.clear_channel_access(ch2)

        if self.channel_member_count(ch1) < self.settings["ALLOWED_USERS"]:
            target_channel = ch1
            player_label = self.settings["PLAYER_LABELS"][0]
            other_label = self.settings["PLAYER_LABELS"][1]
        elif self.channel_member_count(ch2) < self.settings["ALLOWED_USERS"]:
            target_channel = ch2
            player_label = self.settings["PLAYER_LABELS"][1]
            other_label = self.settings["PLAYER_LABELS"][0]
        else:
            return await ctx.send("Both channels are occupied. Please wait for the current session to finish.")

        await target_channel.set_permissions(ctx.author, read_messages=True, send_messages=True)

        try:
            await ctx.author.send(
                f"💥 You have been added to a private channel — go to {target_channel.mention} to start playing."
            )
        except Exception:
            await ctx.send(f"💥 {ctx.author.mention}, you were added to **{player_label}**.")

        # Flavor messages
        rocket_mention = chosen_channel.mention if chosen_channel else ctx.channel.mention
        await ctx.send(random.choice([
            f"🎭 **Caller 1** is lurking in the Talk Room…\n@everyone dare to click **Talk to Stranger** in {rocket_mention} and claim the spot of Caller 2?",
            f"💘 Caller 1 waits in the shadows…\n@everyone who’s brave enough to smash **Talk to Stranger** in {rocket_mention} and become Caller 2?",
            f"🔥 The arena crackles with tension! Caller 1 is ready…\n@everyone click **Talk to Stranger** in {rocket_mention} to step in as Caller 2!",
            f"😼 Meowth whispers: ‘Caller 1 is getting lonely…’\n@everyone time to hit **Talk to Stranger** in {rocket_mention} and spice things up as Caller 2!",
            f"🚀 Jessie shouts: ‘One seat taken, one seat left!’\n@everyone tap **Talk to Stranger** in {rocket_mention} to jump in as Caller 2!"
        ]))

        welcome = (
            f"💥 Welcome, {player_label}! 💥\n"
            f"You are {player_label}, and your chat partner is {other_label}.\n"
            f"👉 Click the **Start 💬** button below to send your first message!\n"
            f"⏱ If {other_label} doesn't reply in {self.settings['REPLY_MINUTE']} minute(s), the session ends."
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

        # Only proceed if session is active
        guild_id = message.guild.id
        if not self.ongoing_sessions.get(guild_id, False):
            return

        # Determine target channel & labels
        if message.channel.id == self.settings["CHANNEL_1_ID"]:
            target_channel = self.bot.get_channel(self.settings["CHANNEL_2_ID"])
            masked_name = self.settings["PLAYER_LABELS"][0]
            target_name = self.settings["PLAYER_LABELS"][1]
        else:
            target_channel = self.bot.get_channel(self.settings["CHANNEL_1_ID"])
            masked_name = self.settings["PLAYER_LABELS"][1]
            target_name = self.settings["PLAYER_LABELS"][0]

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

    # ---------------- Countdowns ----------------
    async def turn_countdown(self, channel: discord.TextChannel, sent: discord.Message):
        total_seconds = self.settings["REPLY_MINUTE"] * 60
        try:
            while total_seconds > 0:
                m, s = divmod(total_seconds, 60)
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
                embed = sent.embeds[0] if sent.embeds else None
                if embed:
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
    await bot.add_cog(TalkToStranger(bot))
