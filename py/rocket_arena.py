# rocket_arena.py
import discord
from discord import app_commands
from discord.ext import commands
from collections import defaultdict
import os
import time

# ===== CONFIG =====
ROCKET_DATE_ARENA_CHANNEL_ID = int(os.getenv("ROCKET_DATE_ARENA_CHANNEL_ID", 0))
ROCKET_GAMES_ARENA_CHANNEL_ID = int(os.getenv("ROCKET_GAMES_ARENA_CHANNEL_ID", 0))
COUNT_SPAM = 5   # max uses
COOLDOWN = 300   # 5 minutes default

GEMS = "💎"
HOURGLASS = "⏳"


# -------------------- CUSTOM VIEW --------------------
class ArenaView(discord.ui.View):
    def __init__(self, bot, user: discord.User, button_data: list):
        super().__init__(timeout=None)
        self.bot = bot
        self.user = user
        self.clicked = set()  # track per-user clicked buttons

        for label, cid, style in button_data:
            self.add_item(ArenaButton(bot, user, cid, label, style, self))


class ArenaButton(discord.ui.Button):
    def __init__(self, bot, user, custom_id, label, style, parent_view):
        super().__init__(label=label, style=style, custom_id=custom_id)
        self.bot = bot
        self.user = user
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("❌ This menu isn’t for you!", ephemeral=True)
            return

        # record this click
        self.parent_view.clicked.add(self.custom_id)
        self.disabled = True  # disable only this user's button

        # if user clicked all, disable everything for this user
        if all(isinstance(item, discord.ui.Button) and item.custom_id in self.parent_view.clicked
               for item in self.parent_view.children):
            for item in self.parent_view.children:
                item.disabled = True

        try:
            await interaction.message.edit(view=self.parent_view)
        except Exception:
            pass

        # map button IDs → actual prefix commands
        prefix_command_map = {
            "rocket_date": "tr date",
            "compatibility_test": "ct",
            "drawing_date": "dd",
            "fun": "tr",
            "escape_room": "er",
            "campfire_confession": "cc",
            "montage_challenge": "mc",
            "lightning_round": "lr",
            "press_quest": "pq",
            "sabotage_game": "pi",
            "poke_bag": "pokebag",
            "daily_quest": "tr q"
        }

        if self.custom_id in prefix_command_map:
            command_name = prefix_command_map[self.custom_id]
            command = self.bot.get_command(command_name)

            if command:
                # Build a fake context so bot invokes as if user typed it
                ctx = await self.bot.get_context(interaction.message)
                ctx.command = command
                ctx.author = interaction.user
                ctx.channel = interaction.channel   # ✅ now runs in current channel
                await interaction.response.defer(ephemeral=True)
                await self.bot.invoke(ctx)
                return

        await interaction.response.send_message("⚠️ That button is not set up yet.", ephemeral=True)


# -------------------- MAIN COG --------------------
class RocketArena(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.cooldowns = defaultdict(list)   # user_id: [timestamps]

    def check_cooldown(self, user_id):
        now = time.time()
        timestamps = self.cooldowns[user_id]
        self.cooldowns[user_id] = [t for t in timestamps if now - t < COOLDOWN]

        if len(self.cooldowns[user_id]) >= COUNT_SPAM:
            return False
        self.cooldowns[user_id].append(now)
        return True

    # ---------- DATE ARENA ----------
    @app_commands.command(name="rocket-date-arena", description="Pick your date activity and earn gems!")
    async def rocket_date_arena(self, interaction: discord.Interaction):
        if interaction.channel.id != ROCKET_DATE_ARENA_CHANNEL_ID:
            await interaction.response.send_message(
                f"❌ This command can only be used in <#{ROCKET_DATE_ARENA_CHANNEL_ID}>.",
                ephemeral=True,
            )
            return

        if not self.check_cooldown(interaction.user.id):
            await interaction.response.send_message(
                f"{HOURGLASS} You reached {COUNT_SPAM} uses! Try again in {COOLDOWN//60} minutes.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="💘 Rocket Date Arena",
            description=f"Hi {interaction.user.mention}, pick an activity and see what gems you might get!\n\n",
            color=discord.Color.purple(),
        )

        button_data = [
            ("💘 Rocket Date  +💎50", "rocket_date", discord.ButtonStyle.green),
            ("💖 Compatibility Test  +💎25", "compatibility_test", discord.ButtonStyle.green),
            ("🎨 Drawing Date  +💎25", "drawing_date", discord.ButtonStyle.green),
            ("🤡 Fun  +💎1", "fun", discord.ButtonStyle.green),
        ]

        view = ArenaView(self.bot, interaction.user, button_data)
        await interaction.response.send_message(embed=embed, view=view)

    # ---------- GAMES ARENA ----------
    @app_commands.command(name="rocket-games-arena", description="Pick a game activity and earn gems!")
    async def rocket_games_arena(self, interaction: discord.Interaction):
        if interaction.channel.id != ROCKET_GAMES_ARENA_CHANNEL_ID:
            await interaction.response.send_message(
                f"❌ This command can only be used in <#{ROCKET_GAMES_ARENA_CHANNEL_ID}>.",
                ephemeral=True,
            )
            return

        if not self.check_cooldown(interaction.user.id):
            await interaction.response.send_message(
                f"{HOURGLASS} You reached {COUNT_SPAM} uses! Try again in {COOLDOWN//60} minutes.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="🎮 Rocket Games Arena",
            description=f"Hi {interaction.user.mention}, pick a game and see what gems you might get!\n\n",
            color=discord.Color.blue(),
        )

        button_data = [
            ("🚪🔐 Escape Room  +💎5/3", "escape_room", discord.ButtonStyle.blurple),
            ("🔥 Campfire Confession  +💎5/3", "campfire_confession", discord.ButtonStyle.blurple),
            ("📸 Montage Challenge  +💎5/3", "montage_challenge", discord.ButtonStyle.blurple),
            ("⚡ Lightning Round  +💎15/5", "lightning_round", discord.ButtonStyle.blurple),
            ("📜 Press Quest (Quick Blast-Off Survey)  +💎15", "press_quest", discord.ButtonStyle.blurple),
            ("🌞 Daily Quest (Quick Blast-Off Survey)  +💎100", "daily_quest", discord.ButtonStyle.blurple),
            ("🎒 Pokebag", "poke_bag", discord.ButtonStyle.blurple),
            ("💣 Sabotage Game  +💎100-500", "sabotage_game", discord.ButtonStyle.blurple)
        ]

        view = ArenaView(self.bot, interaction.user, button_data)
        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(RocketArena(bot))
