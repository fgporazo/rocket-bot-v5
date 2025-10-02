import discord
import random
import json
import os
from discord.ext import commands
from helpers import (award_points)

# ----------- BUTTONS & VIEWS -----------
class AnswerButton(discord.ui.Button):
    def __init__(self, label, index, parent_view):
        super().__init__(label=label, style=discord.ButtonStyle.primary)
        self.index = index
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        user = interaction.user
        if user.id not in [self.parent_view.user1.id, self.parent_view.user2.id]:
            return await interaction.response.send_message(
                "🚫 You're not part of this chaotic test!", ephemeral=True
            )
        if user.id in self.parent_view.answered:
            return await interaction.response.send_message(
                "❌ You've already answered this question! Jessie and James are watching…", ephemeral=True
            )

        self.parent_view.answers[user.id] = str(self.index + 1)
        self.parent_view.answered.add(user.id)

        disabled_view = discord.ui.View()
        for child in self.parent_view.children:
            if isinstance(child, discord.ui.Button):
                disabled_view.add_item(
                    discord.ui.Button(label=child.label, style=child.style, disabled=True)
                )

        await interaction.response.send_message(
            f"✅ Answer locked: **{self.label}** Meowth is noting it down…",
            view=disabled_view, ephemeral=True
        )

        if self.parent_view.have_both_answered():
            await interaction.message.edit(view=None)
            if self.parent_view.is_last_question:
                await interaction.channel.send(
                    "🔔 Both answered! Team Rocket is watching… Calculating results! 💣"
                )
            else:
                await interaction.channel.send(
                    "🔔 Both answered! Jessie screams, James cries, Meowth plots… Moving to the next question! 😼"
                )
            self.parent_view.stop()


class CompatibilityView(discord.ui.View):
    def __init__(self, user1, user2, options, timeout=30, is_last_question=False):
        super().__init__(timeout=timeout)
        self.user1 = user1
        self.user2 = user2
        self.answers = {}
        self.answered = set()
        self.is_last_question = is_last_question

        for i, opt in enumerate(options):
            self.add_item(AnswerButton(opt, i, self))

    def have_both_answered(self):
        return len(self.answered) == 2


# ----------- COG -----------
class CompatibilityTest(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_tests = {}

        # Single channel ID from environment variables
        self.test_channel_id = int(os.getenv("ADMIN_COMPATIBILITY_TEST_CHANNEL_ID", 0))
        if not self.test_channel_id:
            print("[WARNING] ADMIN_COMPATIBILITY_TEST_CHANNEL_ID not set!")

    async def fetch_json_file(self, filename: str):
        """Fetch and decode a JSON file from the configured channel."""
        channel = self.bot.get_channel(self.test_channel_id)
        if not channel:
            return None
        async for message in channel.history(limit=50):
            if message.attachments:
                for attachment in message.attachments:
                    if attachment.filename == filename:
                        data_bytes = await attachment.read()
                        try:
                            return json.loads(data_bytes.decode("utf-8"))
                        except Exception as e:
                            print(f"[ERROR] Failed to load {filename}: {e}")
                            return None
        return None

    @commands.command(name="ct")
    async def compatibility_test(self, ctx, member: discord.Member = None):
        """Start a Team Rocket dramatic compatibility test."""
        if not member:
            help_text = f"`.ct @username` - mention who you want to take compatibility test."
            await ctx.send(f"📖 **Team Rocket Compatibility Test Commands Guide**\n{help_text}")
        if ctx.channel.id in self.active_tests:
            return await ctx.send("🚫 A test is already in progress in this channel!")

        if member.bot:
            return await ctx.send("🚫 You can't test compatibility with a bot!")

        if member == ctx.author and not ctx.author.guild_permissions.administrator:
            return await ctx.send("🚫 You can't test compatibility with yourself!")

        self.active_tests[ctx.channel.id] = True

        # Fetch JSONs
        test_data = await self.fetch_json_file("compatibility_test.json")
        gif_data = await self.fetch_json_file("compatibility_gifs.json")

        if not test_data or not gif_data:
            await ctx.send("⚠️ Could not load compatibility data. Please upload both JSON files.")
            self.active_tests.pop(ctx.channel.id, None)
            return

        # Dramatic start
        await ctx.send(
            f"💘 **Team Rocket Compatibility Test!** 💘\n"
            f"{ctx.author.mention} vs {member.mention} — Prepare for chaos, love, and utter destruction! 😈\n"
            f"⚡ Jessie, James, and Meowth are watching… will you survive their judgment?"
        )

        # Choose topic/questions
        topic = random.choice(test_data["topics"])
        questions = topic["questions"]
        all_answers = {ctx.author.id: [], member.id: []}

        await ctx.send(
            f"🎭 **Topic:** {topic['title']}\n_{topic['desc']}_\n"
            f"💥 Answer wisely… or risk Giovanni’s wrath! 🐾"
        )

        # Question loop
        for idx, q in enumerate(questions, start=1):
            is_last = idx == len(questions)

            embed = discord.Embed(
                title=f"Q{idx}: {q['question']}",
                description="⚡ Choose your answer using the buttons below!",  # no choices shown
                color=discord.Color.purple()
            )
            embed.set_footer(
                text=f"⏳ You have {q['countdown']} seconds to answer… or suffer Team Rocket’s wrath!"
            )

            view = CompatibilityView(
                ctx.author, member, q["options"],
                timeout=q["countdown"], is_last_question=is_last
            )
            msg = await ctx.send(embed=embed, view=view)

            # Wait for answers or timeout
            await view.wait()

            if not view.have_both_answered():
                await msg.edit(view=None)
                await ctx.send(
                    "⌛ Time’s up! Jessie fell asleep, James ran away, and Meowth stole the snacks. "
                    "The compatibility test has **failed**! ❌"
                )
                self.active_tests.pop(ctx.channel.id, None)
                return

            # Store answers
            for uid in [ctx.author.id, member.id]:
                all_answers[uid].append(view.answers.get(uid, "N/A"))

            # Disable buttons after each question
            await msg.edit(view=None)

        # Calculate percentage
        matches = sum(
            all_answers[ctx.author.id][i] == all_answers[member.id][i]
            for i in range(len(questions))
        )
        percentage = (matches / len(questions)) * 100
        # Award points to both players (pass actual Member objects!)
        await award_points(self.bot, ctx.author, 25, notify_channel=ctx.channel)
        await award_points(self.bot, member, 25, notify_channel=ctx.channel)
        # Pick GIF/comment dynamically from GIF JSON
        if percentage == 100:
            key = "success"
        elif percentage >= 60:
            key = "great"
        elif percentage >= 40:
            key = "average"
        else:
            key = "disaster"

        result_data = gif_data.get(key, {})
        comment = result_data.get("comment", "🤔 No comment found!")
        gifs = result_data.get("gifs", [])
        gif_url = random.choice(gifs) if gifs else None

        embed = discord.Embed(
            title="🎉 Compatibility Test Results! 🎉",
            description=f"{ctx.author.mention} ❤️ {member.mention}\n"
                        f"**Match Score:** `{percentage:.0f}%`\n{comment}",
            color=discord.Color.purple()
        )

        if gif_url:
            embed.set_image(url=gif_url)

        await ctx.send(embed=embed)
        self.active_tests.pop(ctx.channel.id, None)


async def setup(bot):
    await bot.add_cog(CompatibilityTest(bot))
