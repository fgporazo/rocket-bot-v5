# mystery_date_cog.py
import asyncio
import random
import discord
from discord.ext import commands
from typing import Optional
import os
from helpers import (award_points)

def has_any_role(member: discord.Member, role_names: set) -> bool:
    """Check if member has any of the specified roles."""
    return any(role.name in role_names for role in member.roles)

class StartButton(discord.ui.View):
    """Button for Player 1 to start the Mystery Date conversation."""
    def __init__(self, other_channel: discord.TextChannel):
        super().__init__(timeout=None)
        self.other_channel = other_channel

    @discord.ui.button(label="Start", style=discord.ButtonStyle.success, emoji="💌")
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            # Send "hi" into the other player's channel
            await self.other_channel.send("hi")

            # Notify Player 2 that the game has started
            await self.other_channel.send("💕 Your mystery date has started! Player 1 just said hi!")

            # Ephemeral confirmation for Player 1
            await interaction.response.send_message("✅ You started the game with a 'hi'!", ephemeral=True)

            # Disable further clicks
            self.stop()
        except Exception as e:
            await interaction.response.send_message(f"❌ Couldn't send start message: {e}", ephemeral=True)


class MysteryDate(commands.Cog):
    """Mystery Date cog with masked relay, countdowns, and anonymous Team Rocket messages."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active_games: dict[int, dict] = {}   # channel.id -> {"task": asyncio.Task, "last_message": discord.Message}
        self.settings: dict = {}
        self.settings_loaded = False
        self.ongoing_dates: dict[int, bool] = {}  # guild.id -> True/False

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
                "ROCKET_BOT_CHANNEL_ID": int(parsed.get("ROCKET_BOT_CHANNEL_ID", 0)),
                "PLAYER_LABELS": [v.strip() for v in parsed.get("PLAYER_LABELS", "Player 1,Player 2").split(",")],
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
        """Reset per-member overwrites (fresh for new game)."""
        for m in channel.members:
            if not m.bot:
                try:
                    await channel.set_permissions(m, overwrite=None)
                except Exception:
                    pass

    async def end_game(self, channel_1: discord.TextChannel, channel_2: discord.TextChannel, reason: str):
        """End the game, reset state, announce anonymously, and award points to players."""
        players = []

        # Collect members (exclude bots)
        for ch in (channel_1, channel_2):
            if not ch:
                continue
            members = [m for m in ch.members if not m.bot]
            players.extend(members)
            # Reset permissions
            for m in members:
                try:
                    await ch.set_permissions(m, overwrite=None)
                except Exception:
                    pass
            # Announce game end in their channels
            try:
                await ch.send(f"🚨 Game ended: {reason}")
            except Exception:
                pass

        # Award points and DM each player
        for player in players:
            try:
                await award_points(self.bot, player, 10, dm=True)  # dm=True sends DM
            except Exception as e:
                print(f"[DEBUG] Could not award points to {player}: {e}")

        # Remove game from active
        for key in list(self.active_games.keys()):
            task = self.active_games[key].get("task")
            if task and not task.done():
                task.cancel()
            self.active_games.pop(key, None)
        self.ongoing_dates = {}

        # Announce in main Mystery Date channel anonymously
        mystery_channel = channel_1.guild.get_channel(self.settings.get("MYSTERY_CHANNEL_ID", 0))
        if mystery_channel:
            team_rocket_ends = [
                f"🚨 A Mystery Date just ended: {reason}",
                "✨ Jessie whispers: another secret romance fizzled out! Thanks for playing! ✨",
                "😼 Meowth: That’s a wrap — Mystery Date closed! 💕 Hope you enjoyed your secret adventure!",
                "🎭 James sighs: Another anonymous adventure ends! 🌟 Until the next Mystery Date… stay mysterious!",
                "🌌 Wobbuffet: The curtain falls on this Mystery Date! Hope you had fun! ✨"
            ]
            await mystery_channel.send(random.choice(team_rocket_ends))

    # ---------------- Commands ----------------
    @commands.command(name="md")
    async def md_start(self, ctx: commands.Context, action: Optional[str] = None):
        guild = ctx.guild
        if not guild:
            return

        admin_channel_id = int(os.getenv("ADMIN_MYSTERY_CHANNEL_ID", 0))
        admin_channel = guild.get_channel(admin_channel_id)
        if not admin_channel or not await self.load_settings_from_admin(admin_channel):
            return await ctx.send("❌ Settings not ready. Ask an admin.")

        #if ctx.channel.id != self.settings["MYSTERY_CHANNEL_ID"]:
           # return await ctx.send(f"❌ Use this command only in <#{self.settings['MYSTERY_CHANNEL_ID']}>.")

        if action != "start":
            return await ctx.send("❌ Wrong usage! Use `.md start` to begin.")

        if not has_any_role(ctx.author, {"Catching PokeMen", "Catching PokeWomen", "Catching 'em all"}):
            return await ctx.send(
                f"❌ Only contestants with Catching roles can join.\n"
                f"Assign one in <#{self.choose_roles_channel_id}>."
            )

        if self.ongoing_dates.get(guild.id, False):
            return await ctx.send("⛔ A Mystery Date is already running — wait for it to finish!")

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
            return await ctx.send("Both channels are occupied. Please wait for the current game to finish.")

        await target_channel.set_permissions(ctx.author, read_messages=True, send_messages=True)
        self.ongoing_dates[guild.id] = True

        try:
            await ctx.author.send(
                f"💥 You have been added to a Mystery Date Arena — go to {target_channel.mention} to start playing."
            )
        except Exception:
            await ctx.send(f"💥 {ctx.author.mention}, you were added to **{player_label}**.")

        # Public flavor message
        await ctx.send(random.choice([
            "🚀 Jessie and James spotted a new recruit in Mystery Date…check your DMs 👀",
            "💥 A mysterious figure entered Mystery Date… Team Rocket is watching! Check your DMs 👀"
        ]))

        await ctx.send(random.choice([
            f"🎭 **Player 1** is lurking in the Mystery Room…\n@everyone dare to click **Mystery Date** in {ctx.channel.mention} and claim the spot of Player 2?",
            f"💘 Player 1 waits in the shadows…\n@everyone who’s brave enough to smash **Mystery Date** in {ctx.channel.mention} and become Player 2?",
            f"🔥 The arena crackles with tension! Player 1 is ready…\n@everyone click **Mystery Date** in {ctx.channel.mention} to step in as Player 2!",
            f"😼 Meowth whispers: ‘Player 1 is getting lonely…’\n@everyone time to hit **Mystery Date** in {ctx.channel.mention} and spice things up as Player 2!",
            f"🚀 Jessie shouts: ‘One seat taken, one seat left!’\n@everyone tap **Mystery Date** in {ctx.channel.mention} to jump in as Player 2!"
        ]))

        welcome = (
            f"💥 Welcome, {player_label}! 💥\n"
            f"You are {player_label}, and your mystery date is {other_label}.\n"
            f"👉 Click the **Start 💌** button below to send your first message!\n"
            f"⏱ If {other_label} doesn't reply in {self.settings['REPLY_MINUTE']} minute(s), the game ends."
        )

        # Figure out where "hi" should go
        other_channel = ch2 if target_channel.id == ch1.id else ch1

        view = StartButton(other_channel)
        sent = await target_channel.send(welcome, view=view)

        if player_label == self.settings["PLAYER_LABELS"][0]:
            task = asyncio.create_task(self.live_countdown(sent, self.settings["REPLY_MINUTE"], other_label, guild.id))
            self.active_games[target_channel.id] = {"task": task, "last_message": sent}

    # ---------------- Listeners ----------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not self.settings_loaded:
            return
        if message.channel.id == self.settings.get("MYSTERY_CHANNEL_ID"):
            return

        if message.channel.id == self.settings["CHANNEL_1_ID"]:
            target_channel = self.bot.get_channel(self.settings["CHANNEL_2_ID"])
            masked_name = self.settings["PLAYER_LABELS"][0]
            target_name = self.settings["PLAYER_LABELS"][1]
        elif message.channel.id == self.settings["CHANNEL_2_ID"]:
            target_channel = self.bot.get_channel(self.settings["CHANNEL_1_ID"])
            masked_name = self.settings["PLAYER_LABELS"][1]
            target_name = self.settings["PLAYER_LABELS"][0]
        else:
            return
        if not target_channel:
            return

        try:
            await message.delete()
        except Exception:
            pass

        await message.channel.send(
            self.settings["SEND_CONFIRMATION_TEMPLATE"].format(
                target_name=target_name, content=message.content
            )
        )

        embed = discord.Embed(description=message.content, color=discord.Color.green())
        embed.set_author(name=masked_name)
        minutes, seconds = divmod(self.settings["REPLY_MINUTE"] * 60, 60)
        embed.set_footer(text=self.settings["FOOTER_TEMPLATE"].format(
            tip=self.settings["TIP_TEXT"], minutes=minutes, seconds=seconds
        ))
        sent = await target_channel.send(embed=embed)

        prev = self.active_games.get(message.channel.id)
        if prev:
            if prev.get("task") and not prev["task"].done():
                prev["task"].cancel()

        task = asyncio.create_task(self.turn_countdown(message.channel, sent))
        self.active_games[message.channel.id] = {"task": task, "last_message": sent}

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
            self.ongoing_dates.pop(guild_id, None)
        except asyncio.CancelledError:
            return


async def setup(bot: commands.Bot):
    await bot.add_cog(MysteryDate(bot))
