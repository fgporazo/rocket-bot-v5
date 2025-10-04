import os
import json
import random
import asyncio
import discord
from datetime import datetime, timedelta
from discord.ext import commands
from discord import app_commands
from helpers import award_points, is_admin  # your helpers

ADMIN_ROCKET_LIST_CHANNEL_ID = int(os.getenv("ADMIN_ROCKET_LIST_CHANNEL_ID", 0))
CATCH_CHANNEL_ID = int(os.getenv("CATCH_CHANNEL_ID", 0))

CATCH_TITLES = [
    "🚨 {pokemon} spotted nearby! Catch it before it escapes! 🏃‍♂️💨",
    "🎯 Target locked: {pokemon}! Deploy capture gadgets!",
    "💥 Wild {pokemon} is causing chaos — Team Rocket, move out!",
    "⚡ {pokemon} detected on the radar! Prepare the Rocket Net!",
    "🪤 {pokemon} appeared unexpectedly! Don’t let it get away!"
]

SUCCESS_LINES = [
    "🎉 Jessie: ‘Another one caught! Giovanni’s gonna give us a raise!’",
    "😼 Meowth: ‘That’s how Team Rocket rolls! {pokemon} never stood a chance!’",
    "💅 James: ‘Grace, style, and success — {pokemon} is ours!’",
    "🚀 Jessie: ‘To protect the world from devastation... and to collect rare Pokémon!’",
    "💎 Meowth: ‘{pokemon} caught! Now that’s what I call a payday!’"
]

FAIL_LINES = [
    "💨 Jessie: ‘Ugh! {pokemon} slipped through our fingers again!’",
    "😿 Meowth: ‘Our gadgets failed! Back to the drawing board!’",
    "💔 James: ‘I knew we should’ve tested the Hypno-Ray first!’",
    "⚡ Jessie: ‘{pokemon} escaped?! How humiliating!’",
    "💥 Meowth: ‘Blasted off again... without even catching it!’"
]


# -----------------------------
# Custom admin check decorator
# -----------------------------
def admin_only():
    async def predicate(interaction: discord.Interaction) -> bool:
        return is_admin(interaction.user)
    return app_commands.check(predicate)


# -----------------------------
# Catch View with dynamic buttons
# -----------------------------
class CatchView(discord.ui.View):
    def __init__(self, bot, pokemon, next_callback, timeout_seconds=3600):
        super().__init__(timeout=None)
        self.bot = bot
        self.pokemon = pokemon
        self.answered = False
        self.next_callback = next_callback
        self.timeout_seconds = timeout_seconds

        # Shuffle gadget choices
        choices_list = list(pokemon["choices"].items())
        random.shuffle(choices_list)

        for choice, desc in choices_list:
            button = discord.ui.Button(
                label=f"💛 {choice}",
                style=discord.ButtonStyle.secondary
            )
            button.callback = self.make_callback(choice, desc)
            self.add_item(button)

        asyncio.create_task(self.fallback_task())

    def make_callback(self, choice, desc):
        async def callback(interaction: discord.Interaction):
            user = interaction.user
            rc_cog = self.bot.get_cog("RocketCatch")
            now = datetime.utcnow()

            # Reset user attempts if 1 hour passed since last try
            if user.id in rc_cog.user_attempts:
                last_time = rc_cog.user_attempts[user.id]["last"]
                if now - last_time > timedelta(hours=1):
                    rc_cog.user_attempts[user.id] = {"count": 0, "last": now}

            # Check cooldown
            cooldown_end = rc_cog.cooldowns.get(user.id)
            if cooldown_end and now < cooldown_end:
                remaining = int((cooldown_end - now).total_seconds() / 60)
                await interaction.response.send_message(
                    f"⏱️ You’re on cooldown for another {remaining} minutes due to excessive catching!",
                    ephemeral=True
                )
                return

            # Update attempts
            data = rc_cog.user_attempts.get(user.id, {"count": 0, "last": now})
            data["count"] += 1
            data["last"] = now
            rc_cog.user_attempts[user.id] = data

            # Apply cooldown if reached 10
            if data["count"] >= 10:
                rc_cog.cooldowns[user.id] = now + timedelta(minutes=30)
                rc_cog.user_attempts[user.id] = {"count": 0, "last": now}
                await interaction.response.send_message(
                    "🚫 You’ve caught too many Pokémon too fast! You’re on a 30-minute cooldown!",
                    ephemeral=True
                )
                return

            # Proceed with normal catching logic
            if self.answered:
                await interaction.response.send_message("❌ Someone already made the choice!", ephemeral=True)
                return
            self.answered = True

            await interaction.response.defer(ephemeral=True)

            for child in self.children:
                child.disabled = True
            await interaction.message.edit(view=self)

            is_correct = "✅" in desc
            pokemon_name = self.pokemon["pokemon"]

            if is_correct:
                title = f"✅ {user.display_name} caught **{pokemon_name}!**"
                line = random.choice(SUCCESS_LINES).format(pokemon=pokemon_name)
                color = discord.Color.green()
                await award_points(self.bot, user, 3, notify_channel=interaction.channel)
            else:
                title = f"❌ {user.display_name} chose a Wrong Gadget! Failed to catch **{pokemon_name}!**"
                line = random.choice(FAIL_LINES).format(pokemon=pokemon_name)
                color = discord.Color.red()

            embed = discord.Embed(title=title, description=line, color=color)
            embed.set_thumbnail(url=self.pokemon.get("img_url", ""))
            await interaction.followup.send(embed=embed, ephemeral=False)

            reason = f"*{choice} — {desc.replace('✅ ', '').replace('❌ ', '')}*"
            await interaction.followup.send(reason, ephemeral=True)

            await asyncio.sleep(2)
            if self.next_callback:
                await self.next_callback()
        return callback

    async def fallback_task(self):
        await asyncio.sleep(self.timeout_seconds)
        if not self.answered:
            self.answered = True
            for child in self.children:
                child.disabled = True
            try:
                if self.message:
                    await self.message.edit(view=self)
            except Exception:
                pass

            pokemon_name = self.pokemon["pokemon"]
            embed = discord.Embed(
                title=f"⏱️ Time's up! No one caught **{pokemon_name}**",
                description="Better luck next time, Team Rocket!",
                color=discord.Color.dark_gray()
            )
            channel = self.bot.get_channel(CATCH_CHANNEL_ID)
            if channel:
                await channel.send(embed=embed)

            if self.next_callback:
                await self.next_callback()


# -----------------------------
# Rocket Catch Cog
# -----------------------------
class RocketCatch(commands.Cog):
    """🚀 Team Rocket Pokémon Capture Event"""

    def __init__(self, bot):
        self.bot = bot
        self.pokemon_data = []
        self.pokemon_queue = []
        self.user_attempts = {}  # {user_id: {"count": int, "last": datetime}}
        self.cooldowns = {}  # {user_id: datetime}

    async def load_latest_json_from_channel(self):
        """Fetch the latest JSON attachment from admin upload channel."""
        channel = self.bot.get_channel(ADMIN_ROCKET_LIST_CHANNEL_ID)
        if not channel:
            print("⚠️ Admin channel not found.")
            return []

        async for message in channel.history(limit=10):
            if message.attachments:
                for attachment in message.attachments:
                    if attachment.filename.endswith(".json"):
                        data = await attachment.read()
                        try:
                            return json.loads(data.decode("utf-8"))
                        except Exception as e:
                            print(f"⚠️ Failed to parse JSON: {e}")
                            return []
        print("⚠️ No JSON attachment found in admin channel.")
        return []

    async def post_next_pokemon(self):
        if not self.pokemon_data:
            self.pokemon_data = await self.load_latest_json_from_channel()
            if not self.pokemon_data:
                print("⚠️ No Pokémon data found.")
                return
            self.pokemon_queue = self.pokemon_data.copy()
            random.shuffle(self.pokemon_queue)

        if not self.pokemon_queue:
            self.pokemon_queue = self.pokemon_data.copy()
            random.shuffle(self.pokemon_queue)

        pokemon = self.pokemon_queue.pop()
        title = random.choice(CATCH_TITLES).format(pokemon=pokemon["pokemon"])

        embed = discord.Embed(
            title=title,
            description=pokemon.get("description", ""),
            color=discord.Color.gold()
        )
        embed.set_thumbnail(url=pokemon.get("img_url", ""))

        channel = self.bot.get_channel(CATCH_CHANNEL_ID)
        if not channel:
            print("⚠️ Catch channel not found.")
            return

        view = CatchView(self.bot, pokemon, self.post_next_pokemon)
        msg = await channel.send(embed=embed, view=view)
        view.message = msg

    @app_commands.command(
        name="rocket-catch",
        description="🚀 Launch a Team Rocket Pokémon catch event (Admins only)"
    )
    @admin_only()
    async def rocket_catch(self, interaction: discord.Interaction):
        await interaction.response.send_message("🚀 Launching Team Rocket capture sequence...", ephemeral=True)
        self.pokemon_data = await self.load_latest_json_from_channel()
        if not self.pokemon_data:
            await interaction.followup.send("⚠️ No Pokémon data found in admin channel!", ephemeral=True)
            return
        self.pokemon_queue = self.pokemon_data.copy()
        random.shuffle(self.pokemon_queue)
        await self.post_next_pokemon()

    @rocket_catch.error
    async def on_catch_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.errors.CheckFailure):
            await interaction.response.send_message("❌ Only admins can launch this command!", ephemeral=True)
        else:
            await interaction.response.send_message(f"⚠️ Error: {error}", ephemeral=True)


async def setup(bot):
    await bot.add_cog(RocketCatch(bot))
