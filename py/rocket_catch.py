import os
import json
import random
import asyncio
import discord
from datetime import datetime, timedelta
from discord.ext import commands
from discord import app_commands
from helpers import award_points, is_admin  # your helpers
import re
from collections import defaultdict

ADMIN_ROCKET_LIST_CHANNEL_ID = int(os.getenv("ADMIN_ROCKET_LIST_CHANNEL_ID", 0))
CATCH_CHANNEL_ID = int(os.getenv("CATCH_CHANNEL_ID", 0))

CATCH_TITLES = [
    "🚨 {pokemon} spotted nearby! Catch it before it escapes! 🏃‍♂️💨",
    "🎯 Target locked: {pokemon}! Deploy capture gadgets!",
    "💥 Wild {pokemon} is causing chaos — PokeCandidate, move out!",
    "⚡ {pokemon} detected on the radar! Prepare the Rocket Net!",
    "🪤 {pokemon} appeared unexpectedly! Don’t let it get away!"
]

SUCCESS_LINES = [
    "🎉 Jessie: ‘Another one caught! Giovanni’s gonna give us a raise!’",
    "😼 Meowth: ‘That’s how PokeCandidate rolls! {pokemon} never stood a chance!’",
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

MEDALS = ["🥇", "🥈", "🥉"]  # Top 3 medals
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
                await award_points(self.bot, user, 1, notify_channel=interaction.channel)
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
                description="Better luck next time, PokeCandidate!",
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

    async def load_second_latest_json_from_channel(self):
        """Fetch JSON from the second-most-recent message with a JSON attachment."""
        channel = self.bot.get_channel(ADMIN_ROCKET_LIST_CHANNEL_ID)
        if not channel:
            print("⚠️ Admin channel not found.")
            return []

        found_count = 0  # counts messages with JSON

        async for message in channel.history(limit=5):
            if message.attachments:
                for attachment in message.attachments:
                    if attachment.filename.endswith(".json"):
                        found_count += 1
                        if found_count == 2:  # second latest JSON message
                            try:
                                data = await attachment.read()
                                return json.loads(data.decode("utf-8"))
                            except Exception as e:
                                print(f"⚠️ Failed to parse JSON: {e}")
                                return []

        print("⚠️ No second-latest JSON attachment found in last 5 messages.")
        return []

    async def post_next_pokemon(self):
        if not self.pokemon_data:
            self.pokemon_data = await self.load_second_latest_json_from_channel()
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
        self.pokemon_data = await self.load_second_latest_json_from_channel()
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

    @commands.command(name="pokecatch")
    async def pokecatch_lb(self, ctx, arg=None):
        if arg != "lb":
            return

        # Prevent duplicate triggers
        if ctx.channel.id in active_lb:
            await ctx.send("⚠️ Leaderboard is already being calculated, please wait...")
            return
        active_lb.add(ctx.channel.id)

        try:
            channel = self.bot.get_channel(CATCH_CHANNEL_ID)
            if not channel:
                await ctx.send("⚠️ Catch channel not found.")
                return

            counts = defaultdict(int)
            pattern = re.compile(r"💎\s*(\S+)")

            # Scan last 500 messages for gem mentions
            async for msg in channel.history(limit=500):
                matches = pattern.findall(msg.content)
                for name in matches:
                    counts[name] += 1

            if not counts:
                await ctx.send("⚠️ No gem messages found in the last 500 messages.")
                return

            guild = ctx.guild
            legendary_role = discord.utils.get(guild.roles, name="Legendary Catcher 🎯")

            # Sort leaderboard
            sorted_counts = sorted(counts.items(), key=lambda x: x[1], reverse=True)

            # Build leaderboard text
            leaderboard_lines = []
            for idx, (name, score) in enumerate(sorted_counts):
                medal = MEDALS[idx] if idx < len(MEDALS) else ""
                leaderboard_lines.append(f"{medal} {name} - {score} 🎯")
            leaderboard_text = "\n".join(leaderboard_lines)

            # Find top member
            top_name, top_score = sorted_counts[0]
            top_member = next(
                (m for m in guild.members if
                 m.display_name.lower() == top_name.lower() or m.name.lower() == top_name.lower()),
                None
            )

            # Remove role from everyone except top_member
            if legendary_role:
                for member in legendary_role.members:
                    if member != top_member:
                        try:
                            await member.remove_roles(legendary_role)
                        except discord.Forbidden:
                            pass

            # Assign role to top member
            if top_member and legendary_role:
                try:
                    await top_member.add_roles(legendary_role)
                except discord.Forbidden:
                    await ctx.send("I don't have permission to assign the role.")

            # Congratulatory message
            congrats_message = (
                f"🎉 Wow {top_member.mention}! You dominated the Pokémon catch! {legendary_role.mention if legendary_role else ''}"
                if top_member else
                f"💥 Boom! {top_name} is the ultimate catcher! {legendary_role.mention if legendary_role else ''}"
            )

            # --- ONLY ONE EMBED ---
            embed = discord.Embed(
                title="🏆 Pokémon Catch Leaderboard",
                description=f"{congrats_message}\n\n**Leaderboard:**\n{leaderboard_text}",
                color=discord.Color.gold()
            )
            embed.set_footer(text="Be the best Pokémon catcher!")

            await ctx.send(embed=embed)

        finally:
            # Remove lock so next call can run
            active_lb.remove(ctx.channel.id)

async def setup(bot):
    await bot.add_cog(RocketCatch(bot))
