import discord
from discord.ext import commands
from discord.ui import View, Button
import asyncio
import os
import re
from collections import defaultdict
from helpers import award_points
import random

class LightningRound(commands.Cog):
    """Team Rocket Lightning Round Quiz"""

    def __init__(self, bot):
        self.bot = bot
        self.active_game = False
        self.participants = defaultdict(lambda: {"joined": False})
        self.round_scores = defaultdict(int)
        self.admin_channel_id = int(os.getenv("ADMIN_LIGHTNING_ROUND_ID", 0))
        self.current_view = None
        self.questions = []

    @commands.group(name="lr", invoke_without_command=True)
    async def lr(self, ctx):
        """⚡ Lightning Round Commands"""
        commands_list = [f"`.lr {m.name}` - {m.help or 'No description'}" for m in self.lr.commands]
        await ctx.send("📖 **Team Rocket Lightning Round Commands**\n" + "\n".join(commands_list))

    @lr.command(name="start", help="⚡ Start the Lightning Round quiz")
    async def lr_start(self, ctx):
        if self.active_game:
            await ctx.send("⚠️ A Lightning Round is already running!")
            return

        self.active_game = True
        self.participants = defaultdict(lambda: {"joined": False})
        self.round_scores = defaultdict(int)

        admin_channel = self.bot.get_channel(self.admin_channel_id)
        if not admin_channel:
            await ctx.send("⚠️ Admin channel not found!")
            self.active_game = False
            return

        # Fetch last 3 messages: questions, config, leaderboard
        msgs = [msg async for msg in admin_channel.history(limit=3, oldest_first=False)]
        msgs.reverse()  # oldest first

        # 1st message = questions
        self.questions = []
        if len(msgs) >= 1:
            raw_lines = [line.strip() for line in msgs[0].content.splitlines() if line.strip()]
            for line in raw_lines:
                parts = line.split("|")
                if len(parts) >= 3:
                    question = parts[0].strip()
                    choices = [parts[1].strip(), parts[2].strip()]
                    correct_idx = 0 if "(correct)" in parts[1] else 1
                    choices[correct_idx] = choices[correct_idx].replace("(correct)", "").strip()
                    self.questions.append((question, choices, correct_idx))
        if not self.questions:
            await ctx.send("⚠️ No questions found!")
            self.active_game = False
            return

        # 2nd message = config
        ready_seconds = 10
        question_seconds = 5
        if len(msgs) >= 2:
            config_text = msgs[1].content
            match_ready = re.search(r'COUNTDOWN_READY\s*=\s*(\d+)', config_text, re.IGNORECASE)
            if match_ready: ready_seconds = int(match_ready.group(1))
            match_q = re.search(r'COUNTDOWN_QUESTIONS\s*=\s*(\d+)', config_text, re.IGNORECASE)
            if match_q: question_seconds = int(match_q.group(1))

        # Countdown embed
        embed = discord.Embed(
            title="⚡ Lightning Round Incoming!",
            description=f"@everyone Get ready...\n\n⏳ {ready_seconds} seconds remaining...",
            color=discord.Color.red()
        )
        ready_msg = await ctx.send(embed=embed)
        for remaining in range(ready_seconds - 1, -1, -1):
            await asyncio.sleep(1)
            try:
                embed.description = f"@everyone Get ready...\n\n⏳ {remaining} seconds remaining..." if remaining > 0 else f"@everyone Get ready...\n\n🚀 **GO!**"
                await ready_msg.edit(embed=embed)
            except discord.HTTPException:
                break

        # Run questions
        for qnum, (question_text, choices, correct_idx) in enumerate(self.questions, 1):
            if not self.active_game:
                break

            answered_first = None

            class QuestionView(View):
                def __init__(self):
                    super().__init__(timeout=question_seconds)
                    for idx, choice in enumerate(choices):
                        btn = Button(label=choice, style=discord.ButtonStyle.blurple)

                        async def btn_callback(interaction: discord.Interaction, idx=idx):
                            nonlocal answered_first
                            if answered_first is not None:
                                await interaction.response.defer()
                                return

                            self.cog.participants[interaction.user.id]["joined"] = True
                            answered_first = interaction.user.id

                            if idx == correct_idx:
                                self.cog.round_scores[answered_first] += 1
                                msg = f"✅ <@{answered_first}> clicked first and got the point!"
                            else:
                                msg = f"❌ <@{answered_first}> clicked first but it was wrong!"

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
            self.current_view = view

            embed = discord.Embed(
                title=f"⚡ Lightning Round! (Q{qnum})",
                description=f"@everyone {question_text}\nClick your answer below!\n\n⏳ {question_seconds} seconds remaining...",
                color=discord.Color.purple()
            )
            question_msg = await ctx.send(embed=embed, view=view)

            for remaining in range(question_seconds - 1, -1, -1):
                await asyncio.sleep(1)
                if answered_first is not None or not self.active_game:
                    break
                try:
                    embed.description = f"@everyone {question_text}\nClick your answer below!\n\n⏳ {remaining} seconds remaining..." if remaining > 0 else f"@everyone {question_text}\nClick your answer below!\n\n⏰ **TIME’S UP!**"
                    await question_msg.edit(embed=embed, view=view)
                except discord.HTTPException:
                    break

            await view.wait()
            if answered_first is None:
                await ctx.send("❌ No one clicked in time.")

        # --- Game finished: reward 15 💎 ---
        reward_lines = []
        for uid in self.participants:
            member = ctx.guild.get_member(uid)
            if member:
                await award_points(self.bot, member, 15, notify_channel=ctx.channel)
                reward_lines.append(f"🎉 <@{uid}> — +15 💎")

        if reward_lines:
            await ctx.send(embed=discord.Embed(
                title="💎 Lightning Round Rewards",
                description="\n".join(reward_lines),
                color=discord.Color.green()
            ))

        # Update/create leaderboard (3rd message)
        await self.update_leaderboard(admin_channel)
        await self.show_leaderboard(ctx, admin_channel)
        self.active_game = False
        self.current_view = None

    @lr.command(name="end", help="End the current Lightning Round")
    async def lr_end(self, ctx):
        if not self.active_game:
            await ctx.send("⚠️ No active Lightning Round to end.")
            return

        self.active_game = False
        if self.current_view:
            self.current_view.stop()
            self.current_view = None

        reward_lines = []
        for uid in self.participants:
            member = ctx.guild.get_member(uid)
            if member:
                await award_points(self.bot, member, 5, notify_channel=ctx.channel)
                reward_lines.append(f"⚡ <@{uid}> — +5 💎")

        if reward_lines:
            await ctx.send(embed=discord.Embed(
                title="💎 Lightning Round Rewards",
                description="\n".join(reward_lines),
                color=discord.Color.green()
            ))

        admin_channel = self.bot.get_channel(self.admin_channel_id)
        await self.update_leaderboard(admin_channel)

    @lr.command(name="lb", help="Show Lightning Round leaderboard")
    async def lr_leaderboard(self, ctx: commands.Context):
        await self.show_leaderboard(ctx)

    # ------------------------------
    async def update_leaderboard(self, admin_channel):
        msgs = [msg async for msg in admin_channel.history(limit=3, oldest_first=False)]
        msgs.reverse()
        leaderboard_msg = msgs[2] if len(msgs) >= 3 else None

        existing_scores = {}
        if leaderboard_msg and leaderboard_msg.content.strip():
            for line in leaderboard_msg.content.splitlines():
                try:
                    name_id, score = line.split("|")
                    name, uid = name_id.rsplit("-", 1)
                    existing_scores[int(uid.strip())] = int(score.strip())
                except Exception as e:
                    print(f"[ERROR] Failed to parse line '{line}': {e}")

        for uid, score in self.round_scores.items():
            if uid in existing_scores:
                existing_scores[uid] += score
            else:
                existing_scores[uid] = score

        lb_lines = []
        for uid, score in existing_scores.items():
            member = admin_channel.guild.get_member(uid)
            name = member.display_name if member else str(uid)
            lb_lines.append(f"{name} - {uid} | {score}")
        lb_text = "\n".join(lb_lines) if lb_lines else ""

        if leaderboard_msg:
            await leaderboard_msg.edit(content=lb_text)
        else:
            await admin_channel.send(lb_text)

    async def show_leaderboard(self, ctx, admin_channel=None):
        if not admin_channel:
            admin_channel = self.bot.get_channel(self.admin_channel_id)

        msgs = [msg async for msg in admin_channel.history(limit=3, oldest_first=False)]
        msgs.reverse()
        leaderboard_msg = msgs[2] if len(msgs) >= 3 else None

        lb_entries = []
        top_user_id = None
        top_member = None
        parsed_scores = []

        if leaderboard_msg and leaderboard_msg.content.strip():
            for line in leaderboard_msg.content.splitlines():
                try:
                    name_id, score = line.split("|")
                    name, uid = name_id.rsplit("-", 1)
                    parsed_scores.append((name.strip(), int(uid.strip()), int(score.strip())))
                except Exception as e:
                    print(f"[ERROR] Failed to parse line '{line}': {e}")

            parsed_scores.sort(key=lambda x: x[2], reverse=True)

            for i, (name, uid, score) in enumerate(parsed_scores):
                medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else f"{i + 1}️⃣"
                lb_entries.append(f"{medal} {name} — {score} ⭐")

            if parsed_scores:
                top_user_id = parsed_scores[0][1]

                top_member = ctx.guild.get_member(top_user_id)
                if not top_member:
                    try:
                        top_member = await ctx.guild.fetch_member(top_user_id)
                        print(f"[INFO] Fetched top member {top_member.display_name} from API")
                    except discord.NotFound:
                        print(f"[ERROR] Top member with ID {top_user_id} not found in guild")
                        top_member = None
                    except Exception as e:
                        print(f"[ERROR] Unexpected error fetching top member {top_user_id}: {e}")
                        top_member = None
        else:
            lb_entries.append("No scores yet. Type `.lr start` to play!")

        # ---------------- Role Assignment with Debug ----------------
        role_name = "Lightning Ace ⚡"
        lr_role = discord.utils.get(ctx.guild.roles, name=role_name)

        print("---- DEBUG LIGHTNING ROUND ----")
        print("Top member ID:", top_user_id)
        print("Top member object:", top_member)
        print("All guild roles:", [r.name for r in ctx.guild.roles])
        bot_member = ctx.guild.get_member(self.bot.user.id)
        print("Bot top role:", bot_member.top_role.name if bot_member else "None")

        if not lr_role:
            print(f"[ERROR] Role '{role_name}' does not exist! Cannot assign Lightning Ace.")
        else:
            for member in ctx.guild.members:
                if lr_role in member.roles:
                    try:
                        await member.remove_roles(lr_role, reason="Reset Lightning Ace role")
                        print(f"[INFO] Removed role '{role_name}' from {member.display_name}")
                    except discord.Forbidden:
                        print(f"[ERROR] Cannot remove role from {member.display_name}, check bot hierarchy or permissions.")
                    except Exception as e:
                        print(f"[ERROR] Unexpected error removing role from {member.display_name}: {e}")

            if top_member:
                try:
                    await top_member.add_roles(lr_role, reason="Top scorer Lightning Round")
                    print(f"[INFO] Assigned role '{role_name}' to {top_member.display_name}")
                except discord.Forbidden:
                    print(f"[ERROR] Cannot assign role to {top_member.display_name}, check bot hierarchy or permissions.")
                except Exception as e:
                    print(f"[ERROR] Unexpected error assigning role to {top_member.display_name}: {e}")
            else:
                print("[INFO] No top member found to assign the role.")

        embed = discord.Embed(
            title="🏆 Lightning Round Leaderboard",
            description="Smartest Pokécandidates in Rocketverse\n\n" + "\n".join(lb_entries),
            color=discord.Color(int("FFB380", 16))
        )
        embed.set_footer(text="Are you smarter than your Pokécandidate? ⭐")

        # Lightning Ace announcement
        lr_role = discord.utils.get(ctx.guild.roles, name="Lightning Ace ⚡")

        if top_member:
            if lr_role:
                messages = [
                    f"\n🏆 All hail {top_member.mention}! You’ve struck first and earned the {lr_role.mention} crown!",
                    f"\n🏆 Zap! {top_member.mention} is now the {lr_role.mention} — top scorer of the round!",
                    f"\n🏆 Lightning strikes! {top_member.mention} claims the {lr_role.mention} role!",
                    f"\n🏆 Watch out! {top_member.mention} just earned the {lr_role.mention} title!",
                    f"\n🏆 Lightning strikes! {top_member.mention} dominates the leaderboard and is the new {lr_role.mention}!",
                    f"\n🏆 Top of the round goes to {top_member.mention} — {lr_role.mention} achieved!"
                ]
            else:
                # fallback if role doesn't exist
                messages = [
                    f"🏆 All hail {top_member.mention}! You’ve struck first and earned the Lightning Ace crown!",
                ]

            embed.add_field(
                name="",
                value=random.choice(messages),
                inline=False
            )

        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(LightningRound(bot))
