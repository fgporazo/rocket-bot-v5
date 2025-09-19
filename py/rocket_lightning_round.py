import discord
from discord.ext import commands
from discord.ui import View, Button
import asyncio
import os
import re
from collections import defaultdict

class LightningRound(commands.Cog):
    """Team Rocket Lightning Round Quiz (first-click-wins style)"""

    def __init__(self, bot):
        self.bot = bot
        self.active_game = False
        self.leaderboard = defaultdict(int)
        self.round_scores = {}  # temporary scores for current round
        self.admin_channel_id = int(os.getenv("ADMIN_LIGHTNING_ROUND_ID", 0))
        self.current_question_msg = None
        self.current_view = None  # <-- track active question view

    @commands.group(name="lr", invoke_without_command=True)
    async def lr(self, ctx):
        """⚡ Lightning Round Commands"""
        commands_list = [f"`.lr {m.name}` - {m.help or 'No description'}" for m in self.lr.commands]
        await ctx.send("📖 **Team Rocket Lightning Round Commands**\n" + "\n".join(commands_list))

    @lr.command(name="start", help="⚡ Start the Lightning Round quiz")
    async def lr_start(self, ctx):
        if self.active_game:
            await ctx.send("⚠️ A Lightning Round is already running! Please wait for it to finish.")
            return

        self.active_game = True
        self.round_scores = defaultdict(int)

        # Fetch questions from admin channel
        questions = []
        countdown_seconds = 5
        channel = self.bot.get_channel(self.admin_channel_id)

        if channel:
            try:
                msgs = [msg async for msg in channel.history(limit=3, oldest_first=False)]
                msgs.reverse()

                if len(msgs) >= 1:
                    raw_lines = [line.strip() for line in msgs[0].content.split("\n") if line.strip()]
                    for line in raw_lines:
                        parts = line.split("|")
                        if len(parts) >= 3:
                            question = parts[0].strip()
                            choices = [parts[1].strip(), parts[2].strip()]
                            correct_idx = 0 if "(correct)" in parts[1] else 1
                            choices[correct_idx] = choices[correct_idx].replace("(correct)", "").strip()
                            questions.append((question, choices, correct_idx))

                if len(msgs) >= 2:
                    match = re.search(r'COUNTDOWN\s*=\s*(\d+)', msgs[1].content.strip(), re.IGNORECASE)
                    if match:
                        countdown_seconds = int(match.group(1))
            except Exception as e:
                print(f"[DEBUG] Error fetching messages: {e}")

        # Fallback questions
        if not questions:
            questions = [
                ("What is the value of pi (approx)?", ["3.14", "3.41"], 0),
                ("How many planets are in the solar system?", ["8", "9"], 0),
                ("Who discovered gravity?", ["Newton", "Einstein"], 0),
            ]

        await ctx.send("@everyone ⚡ Lightning Round is starting! Get ready...")
        await asyncio.sleep(3)

        # Run each question
        for qnum, (question_text, choices, correct_idx) in enumerate(questions, 1):
            if not self.active_game:
                break  # stop if admin ended round

            answered_first = None
            timed_out = False

            class QuestionView(View):
                def __init__(self):
                    super().__init__(timeout=countdown_seconds)
                    for idx, choice in enumerate(choices):
                        btn = Button(label=choice, style=discord.ButtonStyle.blurple)

                        async def btn_callback(interaction: discord.Interaction, idx=idx, choice=choice):
                            nonlocal answered_first
                            if answered_first is not None:
                                await interaction.response.defer()
                                return

                            answered_first = interaction.user.id
                            if idx == correct_idx:
                                self.cog.round_scores[answered_first] += 1
                                msg = f"✅ <@{answered_first}> clicked first and got the point!"
                            else:
                                msg = f"❌ <@{answered_first}> clicked first but it was wrong!"

                            # disable all buttons
                            for child in self.children:
                                child.disabled = True
                            try:
                                await interaction.response.edit_message(view=self)
                            except discord.InteractionResponded:
                                pass

                            await interaction.followup.send(msg, ephemeral=False)
                            self.stop()

                        btn.callback = btn_callback
                        self.add_item(btn)

            view = QuestionView()
            view.cog = self
            self.current_view = view  # <-- track current active view

            embed = discord.Embed(
                title=f"⚡ Lightning Round! (Q{qnum})",
                description=f"@everyone {question_text}\nClick your answer below!",
                color=discord.Color.purple()
            )

            question_msg = await ctx.send(embed=embed, view=view)
            self.current_question_msg = question_msg

            await view.wait()
            if not self.active_game:
                break  # stop loop if ended
            if answered_first is None:
                timed_out = True
                await ctx.send("❌ No one clicked in time.")

            # Show leaderboard after each question
            leaderboard_sorted = sorted(self.round_scores.items(), key=lambda x: x[1], reverse=True)
            lb_lines = []
            for i, (uid, score) in enumerate(leaderboard_sorted):
                if i == 0:
                    medal = "🥇"
                elif i == 1:
                    medal = "🥈"
                elif i == 2:
                    medal = "🥉"
                else:
                    medal = str(i + 1)
                lb_lines.append(f"{medal}. <@{uid}> — {score} pts")

            if lb_lines:
                await ctx.send(embed=discord.Embed(
                    title=f"🏆 Lightning Round Leaderboard (After Q{qnum})",
                    description="\n".join(lb_lines),
                    color=discord.Color.gold()
                ))

            await asyncio.sleep(1)  # small pause before next question

        # Update global leaderboard
        for uid, score in self.round_scores.items():
            self.leaderboard[uid] += score

        # Final summary
        summary_text = []
        final_sorted = sorted(self.leaderboard.items(), key=lambda x: x[1], reverse=True)
        for i, (uid, score) in enumerate(final_sorted):
            if i == 0:
                medal = "🥇"
            elif i == 1:
                medal = "🥈"
            elif i == 2:
                medal = "🥉"
            else:
                medal = str(i + 1)
            summary_text.append(f"{medal}. <@{uid}> — {score} pts")

        if summary_text:
            desc = f"@everyone Final scores:\n" + "\n".join(summary_text)
        else:
            desc = "@everyone No one scored this round."

        await ctx.send(embed=discord.Embed(
            title="⚡ Lightning Round Completed!",
            description=desc,
            color=discord.Color.teal()
        ))

        self.active_game = False
        self.round_scores = {}
        self.current_view = None

    @lr.command(name="end", help="End the current Lightning Round")
    async def lr_end(self, ctx):
        if not self.active_game:
            await ctx.send("⚠️ No active Lightning Round to end.")
            return

        self.active_game = False

        # Stop the current question's View immediately
        if self.current_view:
            self.current_view.stop()
            self.current_view = None

        # Show current leaderboard with medals
        if self.round_scores:
            sorted_lb = sorted(self.round_scores.items(), key=lambda x: x[1], reverse=True)
            lb_lines = []
            for i, (uid, score) in enumerate(sorted_lb):
                if i == 0:
                    medal = "🥇"
                elif i == 1:
                    medal = "🥈"
                elif i == 2:
                    medal = "🥉"
                else:
                    medal = str(i + 1)
                lb_lines.append(f"{medal}. <@{uid}> — {score} pts")

            await ctx.send(embed=discord.Embed(
                title="🏆 Lightning Round Ended!",
                description=f"@everyone Current scores:\n" + "\n".join(lb_lines),
                color=discord.Color.teal()
            ))
        else:
            await ctx.send("@everyone ⚡ The Lightning Round has been ended. No one scored this round.")

        self.round_scores = {}

    @lr.command(name="lb", help="Show the Lightning Round leaderboard")
    async def lr_leaderboard(self, ctx):
        if not self.leaderboard:
            await ctx.send(embed=discord.Embed(
                title="🏆 Lightning Round Leaderboard",
                description="No scores yet! ⚡",
                color=discord.Color.gold()
            ))
            return

        sorted_lb = sorted(self.leaderboard.items(), key=lambda x: x[1], reverse=True)
        lb_lines = []
        for i, (uid, score) in enumerate(sorted_lb):
            if i == 0:
                medal = "🥇"
            elif i == 1:
                medal = "🥈"
            elif i == 2:
                medal = "🥉"
            else:
                medal = str(i + 1)
            lb_lines.append(f"{medal} <@{uid}> — {score} pts")

        await ctx.send(embed=discord.Embed(
            title="🏆 Lightning Round Leaderboard",
            description="Smartest Pokécandidates:\n\n" + "\n".join(lb_lines),
            color=discord.Color.gold()
        ))

async def setup(bot):
    await bot.add_cog(LightningRound(bot))
