import discord
from discord.ext import commands
from discord.ui import View, Button
import asyncio
from collections import defaultdict
import os
import re

def progress_bar(current, total, length=12):
    filled = int(length * current / total)
    empty = length - filled
    return "■" * filled + "□" * empty

class PressQuest(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_sessions = {}  # user_id: session active?
        self.cooldowns = defaultdict(list)  # user_id: [timestamps]

    @commands.group(name="pq", invoke_without_command=True)
    async def pq(self, ctx):
        """🎮 Team Rocket Press Quest Commands Guide"""
        commands_list = [
            f"`.pq {m.name}` - {m.help or 'No description'}"
            for m in self.pq.commands
        ]
        commands_list.sort()
        help_text = "\n".join(commands_list)
        await ctx.send(f"📖 **Team Rocket Press Quest (Quick Blast-Off Survey) Commands Guide**\n{help_text}")

    @pq.command(name="start")
    async def pq_start(self, ctx):
        user_id = ctx.author.id
        now = asyncio.get_event_loop().time()

        # cooldown (3 runs per 5 mins)
        self.cooldowns[user_id] = [t for t in self.cooldowns[user_id] if now - t < 300]
        if len(self.cooldowns[user_id]) >= 3:
            await ctx.send(f"🚫 {ctx.author.mention}, you’re on cooldown! Try again in 5 minutes.")
            return
        self.cooldowns[user_id].append(now)

        if user_id in self.active_sessions:
            await ctx.send(f"⚠️ {ctx.author.mention}, you already have a Press Quest running!")
            return
        self.active_sessions[user_id] = True

        # fetch last 2 messages from admin channel
        channel_id = int(os.getenv("ADMIN_PRESS_QUEST_ID", 0))
        channel = self.bot.get_channel(channel_id)
        questions = []
        countdown_seconds = 30  # default

        if channel:
            try:
                # newest first, then reverse to get oldest first
                msgs = [msg async for msg in channel.history(limit=2, oldest_first=False)]
                msgs.reverse()

                if len(msgs) >= 1:
                    # first message = questions
                    raw_lines = [line.strip() for line in msgs[0].content.split("\n") if line.strip()]
                    for line in raw_lines:
                        q = re.sub(r"^\s*\d+[\.\)]\s*", "", line)
                        questions.append(q)

                if len(msgs) >= 2:
                    # second message = countdown
                    match = re.search(r'COUNTDOWN\s*=\s*(\d+)', msgs[1].content.strip(), re.IGNORECASE)
                    if match:
                        countdown_seconds = int(match.group(1))
            except Exception as e:
                print(f"Error fetching questions/countdown: {e}")

        if not questions:
            # fallback
            questions = [
                "Would you join Team Rocket if Giovanni asked?",
                "Do you trust Meowth to cook your dinner?",
                "Would you let Wobbuffet babysit your Pokémon?",
            ]

        answers = []

        # initial embed
        embed = discord.Embed(
            title=f"Press Quest (Quick Blast-Off Survey)",
            description=f"{ctx.author.mention}, {questions[0]}",
            color=discord.Color.purple()
        )
        bar = progress_bar(countdown_seconds, countdown_seconds)
        embed.set_footer(text=f"💡 Tip: press ✅ for YES or ❌ for NO | Q1/{len(questions)}\n⏳ [{bar}] {countdown_seconds}s")

        view = View(timeout=None)
        yes_btn = Button(emoji="✅", style=discord.ButtonStyle.secondary, custom_id="press_yes")
        no_btn = Button(emoji="❌", style=discord.ButtonStyle.secondary, custom_id="press_no")
        view.add_item(no_btn)
        view.add_item(yes_btn)

        msg = await ctx.send(embed=embed, view=view)

        async def finish_game():
            for child in view.children:
                child.disabled = True
            await msg.edit(view=view)

            result = discord.Embed(
                title=f"📜 Press Quest - (Quick Blast-Off Survey) Results for {ctx.author.display_name}",
                color=discord.Color.teal()
            )
            if answers:
                for i, (q, a) in enumerate(answers, 1):
                    result.add_field(name=f"Q{i}: {q}", value=a, inline=False)
            else:
                result.description = "No answers recorded — you chickened out, twerp!"
            await ctx.send(embed=result)
            if user_id in self.active_sessions:
                del self.active_sessions[user_id]

        async def ask_question(question_text, index, total):
            loop = asyncio.get_event_loop()
            result = {"answered": False}

            async def countdown():
                for remaining in range(countdown_seconds, 0, -1):
                    if result["answered"]:
                        return
                    bar = progress_bar(remaining, countdown_seconds)
                    embed.description = f"{ctx.author.mention}, {question_text}"
                    embed.set_footer(
                        text=f"💡 Tip: press ✅ for YES or ❌ for NO | Q{index+1}/{total}\n⏳ [{bar}] {remaining}s"
                    )
                    try:
                        await msg.edit(embed=embed, view=view)
                    except discord.NotFound:
                        return
                    await asyncio.sleep(1)
                if not result["answered"]:
                    answers.append((question_text, "⏳ No Response"))
                    result["answered"] = True

            async def wait_click():
                try:
                    interaction = await self.bot.wait_for(
                        "interaction",
                        timeout=countdown_seconds,
                        check=lambda i: i.user.id == user_id and i.message.id == msg.id
                    )
                    if interaction.data["custom_id"] == "press_yes":
                        answers.append((question_text, "✅ YES"))
                    elif interaction.data["custom_id"] == "press_no":
                        answers.append((question_text, "❌ NO"))
                    await interaction.response.defer(thinking=False)
                    result["answered"] = True
                except asyncio.TimeoutError:
                    pass

            timer_task = loop.create_task(countdown())
            click_task = loop.create_task(wait_click())
            await asyncio.wait([timer_task, click_task], return_when=asyncio.FIRST_COMPLETED)
            for task in [timer_task, click_task]:
                if not task.done():
                    task.cancel()

        # run all questions dynamically
        for idx, question in enumerate(questions):
            await ask_question(question, idx, len(questions))

        await finish_game()


async def setup(bot):
    await bot.add_cog(PressQuest(bot))
