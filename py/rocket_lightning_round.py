import discord
from discord.ext import commands
from discord.ui import View, Button
import asyncio
import os
import re
from collections import defaultdict
from helpers import award_points


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
        participants = defaultdict(lambda: {"answered": 0, "rewarded_join": False})

        # --- Fetch questions and countdowns ---
        questions = []
        ready_seconds = 10
        question_seconds = 5
        channel = self.bot.get_channel(self.admin_channel_id)

        if channel:
            try:
                msgs = [msg async for msg in channel.history(limit=3, oldest_first=False)]
                msgs.reverse()

                # First message = questions
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

                # Second message = countdown configs
                if len(msgs) >= 2:
                    msg_text = msgs[1].content.strip()

                    match_ready = re.search(r'COUNTDOWN_READY\s*=\s*(\d+)', msg_text, re.IGNORECASE)
                    if match_ready:
                        ready_seconds = int(match_ready.group(1))

                    match_q = re.search(r'COUNTDOWN_QUESTIONS\s*=\s*(\d+)', msg_text, re.IGNORECASE)
                    if match_q:
                        question_seconds = int(match_q.group(1))

            except Exception as e:
                print(f"[DEBUG] Error fetching messages: {e}")

        # Fallback questions if none in admin channel
        if not questions:
            questions = [
                ("What is the value of pi (approx)?", ["3.14", "3.41"], 0),
                ("How many planets are in the solar system?", ["8", "9"], 0),
                ("Who discovered gravity?", ["Newton", "Einstein"], 0),
            ]

        # --- Ready countdown (live) ---
        embed = discord.Embed(
            title="⚡ Lightning Round Incoming!",
            description=f"@everyone Get ready...\n\n⏳ {ready_seconds} seconds remaining...",
            color=discord.Color.red()
        )
        ready_msg = await ctx.send(embed=embed)

        for remaining in range(ready_seconds - 1, -1, -1):
            await asyncio.sleep(1)
            try:
                if remaining > 0:
                    embed.description = f"@everyone Get ready...\n\n⏳ {remaining} seconds remaining..."
                else:
                    embed.description = f"@everyone Get ready...\n\n🚀 **GO!**"
                await ready_msg.edit(embed=embed)
            except discord.HTTPException:
                break

        # --- Run each question ---
        for qnum, (question_text, choices, correct_idx) in enumerate(questions, 1):
            if not self.active_game:
                break  # stop if admin ended round

            answered_first = None

            class QuestionView(View):
                def __init__(self):
                    super().__init__(timeout=question_seconds)
                    for idx, choice in enumerate(choices):
                        btn = Button(label=choice, style=discord.ButtonStyle.blurple)

                        async def btn_callback(interaction: discord.Interaction, idx=idx, choice=choice):
                            nonlocal answered_first
                            if answered_first is not None:
                                await interaction.response.defer()
                                return

                            # Reward joiners once
                            if not participants[interaction.user.id]["rewarded_join"]:
                                participants[interaction.user.id]["rewarded_join"] = True
                                await award_points(self.bot, interaction.user, 1, notify_channel=ctx.channel)
                                await ctx.send(f"✨ <@{interaction.user.id}> joined the Lightning Round — **+1 💎**")

                            participants[interaction.user.id]["answered"] += 1

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
            self.current_view = view  # track current active view

            embed = discord.Embed(
                title=f"⚡ Lightning Round! (Q{qnum})",
                description=f"@everyone {question_text}\nClick your answer below!\n\n⏳ {question_seconds} seconds remaining...",
                color=discord.Color.purple()
            )
            question_msg = await ctx.send(embed=embed, view=view)
            self.current_question_msg = question_msg

            # --- Live countdown for question ---
            for remaining in range(question_seconds - 1, -1, -1):
                await asyncio.sleep(1)
                if answered_first is not None or not self.active_game:
                    break
                try:
                    if remaining > 0:
                        embed.description = f"@everyone {question_text}\nClick your answer below!\n\n⏳ {remaining} seconds remaining..."
                    else:
                        embed.description = f"@everyone {question_text}\nClick your answer below!\n\n⏰ **TIME’S UP!**"
                    await question_msg.edit(embed=embed, view=view)
                except discord.HTTPException:
                    break

            await view.wait()
            if not self.active_game:
                break
            if answered_first is None:
                await ctx.send("❌ No one clicked in time.")

            # --- Leaderboard after each question ---
            leaderboard_sorted = sorted(self.round_scores.items(), key=lambda x: x[1], reverse=True)
            lb_lines = []
            for i, (uid, score) in enumerate(leaderboard_sorted):
                medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else str(i + 1)
                lb_lines.append(f"{medal}. <@{uid}> — {score} pts")

            if lb_lines:
                await ctx.send(embed=discord.Embed(
                    title=f"🏆 Lightning Round Leaderboard (After Q{qnum})",
                    description="\n".join(lb_lines),
                    color=discord.Color.gold()
                ))

            await asyncio.sleep(1)  # pause before next question

        # --- Update global leaderboard ---
        for uid, score in self.round_scores.items():
            self.leaderboard[uid] += score

        # --- Final summary ---
        summary_text = []
        final_sorted = sorted(self.leaderboard.items(), key=lambda x: x[1], reverse=True)
        for i, (uid, score) in enumerate(final_sorted):
            medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else str(i + 1)
            summary_text.append(f"{medal}. <@{uid}> — {score} pts")

        desc = f"@everyone Final scores:\n" + "\n".join(summary_text) if summary_text else "@everyone No one scored this round."

        await ctx.send(embed=discord.Embed(
            title="⚡ Lightning Round Completed!",
            description=desc,
            color=discord.Color.teal()
        ))

        # --- Rewards ---
        total_questions = len(questions)
        reward_lines = []
        for uid, data in participants.items():
            member = ctx.guild.get_member(uid)
            if not member:
                continue

            if data["answered"] == total_questions:
                await award_points(self.bot, member, 50, notify_channel=ctx.channel)
                reward_lines.append(f"🎉 <@{uid}> completed all {total_questions} questions — **+50 💎**")
            elif data["answered"] > 0:
                await award_points(self.bot, member, 5, notify_channel=ctx.channel)
                reward_lines.append(f"⚡ <@{uid}> joined but didn’t finish — **+5 💎**")

        if reward_lines:
            await ctx.send(embed=discord.Embed(
                title="💎 Lightning Round Rewards",
                description="\n".join(reward_lines),
                color=discord.Color.green()
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

        # Stop active view
        if self.current_view:
            self.current_view.stop()
            self.current_view = None

        if self.round_scores:
            sorted_lb = sorted(self.round_scores.items(), key=lambda x: x[1], reverse=True)
            lb_lines = []
            for i, (uid, score) in enumerate(sorted_lb):
                medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else str(i + 1)
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
            medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else str(i + 1)
            lb_lines.append(f"{medal} <@{uid}> — {score} pts")

        await ctx.send(embed=discord.Embed(
            title="🏆 Lightning Round Leaderboard",
            description="Smartest Pokécandidates:\n\n" + "\n".join(lb_lines),
            color=discord.Color.gold()
        ))


async def setup(bot):
    await bot.add_cog(LightningRound(bot))
