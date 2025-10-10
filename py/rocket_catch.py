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
CATCH_CHANNEL_NAME_KEYWORD = "catch"  # Look for channels containing this keyword

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

MEDALS = ["🥇", "🥈", "🥉"]
pokecatch_lock = asyncio.Lock()  # Prevent multiple leaderboards

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

            # Reset attempts after 1 hour
            if user.id in rc_cog.user_attempts:
                last_time = rc_cog.user_attempts[user.id]["last"]
                if now - last_time > timedelta(hours=1):
                    rc_cog.user_attempts[user.id] = {"count": 0, "last": now}

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

            if data["count"] >= 10:
                rc_cog.cooldowns[user.id] = now + timedelta(minutes=30)
                rc_cog.user_attempts[user.id] = {"count": 0, "last": now}
                await interaction.response.send_message(
                    "🚫 You’ve caught too many Pokémon too fast! You’re on a 30-minute cooldown!",
                    ephemeral=True
                )
                return

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

            # Send to the first channel containing "catch"
            for channel in self.bot.get_all_channels():
                if isinstance(channel, discord.TextChannel) and CATCH_CHANNEL_NAME_KEYWORD in channel.name.lower():
                    await channel.send(embed=embed)
                    break

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
        self.user_attempts = {}
        self.cooldowns = {}
        self._lb_running = False

    async def load_second_latest_json_from_channel(self):
        channel = self.bot.get_channel(ADMIN_ROCKET_LIST_CHANNEL_ID)
        if not channel:
            print("⚠️ Admin channel not found.")
            return []

        found_count = 0
        async for message in channel.history(limit=5):
            if message.attachments:
                for attachment in message.attachments:
                    if attachment.filename.endswith(".json"):
                        found_count += 1
                        if found_count == 2:
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

        # Find the first channel containing "catch"
        channel = None
        for ch in self.bot.get_all_channels():
            if isinstance(ch, discord.TextChannel) and CATCH_CHANNEL_NAME_KEYWORD in ch.name.lower():
                channel = ch
                break
        if not channel:
            print("⚠️ Catch channel not found.")
            return

        view = CatchView(self.bot, pokemon, self.post_next_pokemon)
        msg = await channel.send(embed=embed, view=view)
        view.message = msg

    @app_commands.command(
        name="rocket-catch",
        description="Launch a Team Rocket Pokémon catch event (Premium only)"
    )
    @admin_only()
    async def rocket_catch(self, interaction: discord.Interaction):
        # Ensure invoked in a channel containing "catch"
        if CATCH_CHANNEL_NAME_KEYWORD not in interaction.channel.name.lower():
            await interaction.response.send_message(
                "❌ This command can only be used in a channel with 'catch' in its name.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            "🚀 Launching Team Rocket capture sequence...", ephemeral=True
        )
        self.pokemon_data = await self.load_second_latest_json_from_channel()
        if not self.pokemon_data:
            await interaction.followup.send(
                "⚠️ No Pokémon data found in admin channel!", ephemeral=True
            )
            return
        self.pokemon_queue = self.pokemon_data.copy()
        random.shuffle(self.pokemon_queue)
        await self.post_next_pokemon()

    @rocket_catch.error
    async def on_catch_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.errors.CheckFailure):
            await interaction.response.send_message(
                "🚫 Sorry, only Premium members can launch this command.\n"
                "Visit RocketBot's official page to get Premium.",
                ephemeral=True)
        else:
            await interaction.response.send_message(f"⚠️ Error: {error}", ephemeral=True)

    # --- Pokémon Catch Leaderboard ---
    @commands.group(name="pc", invoke_without_command=True)
    async def pc_group(self, ctx):
        """Pokémon Catch group commands"""
        await ctx.send("🎯 Use `!pc lb` to see the Pokémon Catch leaderboard!")

    @pc_group.command(name="lb", aliases=["leaderboard"])
    async def pc_lb(self, ctx):
        """📊 Show Pokémon Catch Leaderboard"""
        if self._lb_running:
            await ctx.send("⚠️ Leaderboard is already being calculated, please wait...")
            return

        self._lb_running = True
        try:
            # Find the first channel containing "catch"
            channel = None
            for ch in self.bot.get_all_channels():
                if isinstance(ch, discord.TextChannel) and CATCH_CHANNEL_NAME_KEYWORD in ch.name.lower():
                    channel = ch
                    break
            if not channel:
                await ctx.send("⚠️ Catch channel not found.")
                return

            temp_msg = await ctx.send("⏳ Calculating Pokémon Catch Leaderboard...")
            counts = defaultdict(int)
            pattern = re.compile(r"💎\s*(\S+)")

            async for msg in channel.history(limit=500):
                matches = pattern.findall(msg.content)
                for name in matches:
                    counts[name] += 1

            if not counts:
                await temp_msg.edit(content="⚠️ No gem messages found in the last 500 messages.")
                return

            sorted_counts = sorted(counts.items(), key=lambda x: x[1], reverse=True)

            leaderboard_lines = [
                f"{MEDALS[i] if i < 3 else '🔹'} {name} — {score} 🎯"
                for i, (name, score) in enumerate(sorted_counts)
            ]
            leaderboard_text = "\n".join(leaderboard_lines)

            guild = ctx.guild
            role_name = "Legendary Catcher 🎯"
            legendary_role = discord.utils.get(guild.roles, name=role_name)

            top_name, top_score = sorted_counts[0]
            top_member = next(
                (m for m in guild.members if m.display_name.lower() == top_name.lower() or m.name.lower() == top_name.lower()),
                None
            )

            if not legendary_role:
                legendary_role = await ctx.guild.create_role(
                    name=role_name,
                    colour=discord.Colour(0x3498DB),
                    reason="Top Pokemon catcher"
                )

            if legendary_role:
                for member in legendary_role.members:
                    if member != top_member:
                        await member.remove_roles(legendary_role, reason="Lost top spot")
                if top_member:
                    await top_member.add_roles(legendary_role, reason="New top catcher")

            congrats = (
                f"🎉 {top_member.mention if top_member else top_name} is the **Top Pokémon Catcher!** "
                f"{legendary_role.mention if legendary_role else ''}"
            )

            embed = discord.Embed(
                title="🏆 Pokémon Catch Leaderboard",
                description=f"{congrats}\n\n{leaderboard_text}",
                color=discord.Color.gold()
            )
            embed.set_footer(text="💫 Congratulations to all trainers — keep catching to claim the top spot!")

            await temp_msg.delete()
            await ctx.send(embed=embed)

        except Exception as e:
            await ctx.send(f"⚠️ An error occurred while generating the leaderboard: `{e}`")
            raise
        finally:
            self._lb_running = False


async def setup(bot):
    await bot.add_cog(RocketCatch(bot))
