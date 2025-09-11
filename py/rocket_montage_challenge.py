import discord
from discord.ext import commands
from discord.ui import View, Button
import asyncio, random, os, time
from collections import defaultdict
from datetime import timedelta
from discord.utils import utcnow

# ---------------- Config ----------------
MIN_TEAM_SIZE = 1
MAX_TEAM_SIZE = 10
JOIN_DURATION = 60
IMAGE_DURATION = 3  # seconds each image stays
COOLDOWN_HOURS = 5
COOLDOWN_SECONDS = 10

ROUND_FOLDERS = [
    "assets/montage/male",
    "assets/montage/female",
    "assets/montage/mix"
]

class MontageChallenge(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_session = None
        self.cooldowns = {}  # user_id -> timestamp

    class Session:
        def __init__(self, channel, host):
            self.channel = channel
            self.host = host
            self.teams = {"A": [], "B": []}
            self.scores = defaultdict(int)
            self.team_scores = {"A": 0, "B": 0}
            self.join_open = True
            self.flashed_images = []
            self.buzz_log = []
            self.teams_buzzed_current = set()
            self.current_duplicate_count = 0

        def add_player(self, user):
            if user in self.teams["A"] or user in self.teams["B"]:
                return False
            # auto-balance
            if len(self.teams["A"]) < len(self.teams["B"]) and len(self.teams["A"]) < MAX_TEAM_SIZE:
                self.teams["A"].append(user)
            elif len(self.teams["B"]) < MAX_TEAM_SIZE:
                self.teams["B"].append(user)
            else:
                if len(self.teams["A"]) < MAX_TEAM_SIZE:
                    self.teams["A"].append(user)
                elif len(self.teams["B"]) < MAX_TEAM_SIZE:
                    self.teams["B"].append(user)
                else:
                    return False
            return True

        def team_of(self, user):
            if user in self.teams["A"]:
                return "A"
            if user in self.teams["B"]:
                return "B"
            return None

    @commands.group(name="mc", invoke_without_command=True)
    async def mc(self, ctx):
        """📖 Team Rocket Montage Challenge Commands Guide"""
        commands_list = [
            f"`.mc {m.name}` - {m.help or 'No description'}"
            for m in self.mc.commands
        ]
        commands_list.sort()
        help_text = "\n".join(commands_list)
        await ctx.send(f"📖 **Team Rocket Montage Challenge Commands Guide**\n{help_text}")

    @mc.command(name="start",help="Start a montage challenge")
    async def mc_start(self, ctx):
        now = time.time()
        if ctx.author.id in self.cooldowns and now - self.cooldowns[ctx.author.id] < COOLDOWN_HOURS * 3600:
            await ctx.send("⏳ You must wait before starting another challenge (5h cooldown).")
            return
        if self.active_session:
            await ctx.send("❌ A session is already running.")
            return

        self.cooldowns[ctx.author.id] = now
        self.active_session = self.Session(ctx.channel, ctx.author)
        self.active_session.teams["A"].append(ctx.author)
        sess = self.active_session
        sess.join_open = True

        join_msg = await ctx.send(f"🎮 {ctx.author.mention} started a Montage Challenge!\n"
                                  f"Team A: {ctx.author.mention}\nTeam B: (empty)\n"
                                  f"Join with `.mc join` ({JOIN_DURATION}s left)...")

        for remaining in range(JOIN_DURATION, 0, -1):
            team_a = ", ".join([m.mention for m in sess.teams["A"]]) or "None"
            team_b = ", ".join([m.mention for m in sess.teams["B"]]) or "None"
            await join_msg.edit(content=f"🎮 Montage Challenge!\nTeam A: {team_a}\nTeam B: {team_b}\n"
                                        f"⏳ Join with `.mc join` ({remaining}s left)...")
            await asyncio.sleep(1)

        sess.join_open = False
        await self.launch_game(ctx)

    @mc.command(name="join",help="Join a team (A / B)")
    async def mc_join(self, ctx):
        if not self.active_session:
            await ctx.send("❌ No active session.")
            return
        if not self.active_session.join_open:
            await ctx.send("❌ Joining closed.")
            return
        sess = self.active_session
        if sess.add_player(ctx.author):
            await ctx.send(f"✅ {ctx.author.mention} joined Team {sess.team_of(ctx.author)}")
        else:
            await ctx.send("⚠️ You are already in a team or teams are full.")

    async def launch_game(self, ctx):
        sess = self.active_session
        if len(sess.teams["A"]) < MIN_TEAM_SIZE or len(sess.teams["B"]) < MIN_TEAM_SIZE:
            await ctx.send("❌ Not enough players. Game canceled.")
            self.active_session = None
            return

        await ctx.send("✅ Teams locked in!")
        await self.show_team_list(ctx)
        await ctx.send("Game starts in 5 seconds...")
        await asyncio.sleep(5)

        for round_idx, folder in enumerate(ROUND_FOLDERS, start=1):
            await self.play_round(ctx, sess, round_idx, folder)

        await self.end_game(ctx, sess)

    async def show_team_list(self, ctx):
        sess = self.active_session
        embed = discord.Embed(title="🏆 Teams", color=discord.Color.purple())
        for t in ["A", "B"]:
            members = "\n".join(m.mention for m in sess.teams[t]) or "None"
            embed.add_field(name=f"Team {t}", value=members, inline=False)
        await ctx.send(embed=embed)

    async def play_round(self, ctx, sess, round_idx, folder):
        images = [os.path.join(folder, f) for f in os.listdir(folder) if not f.startswith(".")]
        if len(images) < 5:
            await ctx.send(f"⚠️ Not enough images in {folder}")
            return

        # Prepare images and duplicates
        loop = random.sample(images, min(10, len(images)))
        duplicates = random.sample(loop, min(3, len(loop)))
        for dup in duplicates:
            insert_pos = random.randint(0, len(loop)-1)
            loop.insert(insert_pos, dup)
        random.shuffle(loop)

        sess.flashed_images = []
        sess.buzz_log = []
        sess.teams_buzzed_current = set()
        sess.current_duplicate_count = len(duplicates)
        ROUND_DURATION = len(loop) * IMAGE_DURATION

        embed = discord.Embed(
            title=f"📸 Round {round_idx}",
            description="👀 Spot duplicates! Press 🚨 BUZZER when you see one.",
            color=discord.Color.blurple()
        )
        embed.add_field(name="Time Remaining", value=f"{ROUND_DURATION}s", inline=False)
        embed.add_field(name="Buzzer 🔔", value="No buzzes yet.", inline=False)
        embed.add_field(name="Duplicates Remaining", value=str(sess.current_duplicate_count), inline=False)

        msg = await ctx.send(embed=embed, view=self.make_buzzer(sess, loop, duplicates, embed))

        remaining_time = ROUND_DURATION
        for current_img in loop:
            sess.flashed_images.append(current_img)
            embed.set_thumbnail(url=f"attachment://{os.path.basename(current_img)}")
            file = discord.File(current_img, filename=os.path.basename(current_img))
            await msg.edit(embed=embed, attachments=[file])

            for _ in range(IMAGE_DURATION):
                if remaining_time <= 0 or sess.current_duplicate_count <= 0:
                    break
                await asyncio.sleep(1)
                remaining_time -= 1
                embed.set_field_at(0, name="Time Remaining", value=f"{remaining_time}s", inline=False)
                await msg.edit(embed=embed)

            sess.teams_buzzed_current.clear()
            if remaining_time <= 0 or sess.current_duplicate_count <= 0:
                break

        await msg.edit(view=None)
        await self.show_scoreboard(ctx, sess, round_idx)
        if round_idx < len(ROUND_FOLDERS):
            await ctx.send("⏱ Next round starts in 5 seconds...")
            await asyncio.sleep(5)

    def make_buzzer(self, sess, loop, duplicates, embed):
        view = View(timeout=None)
        user_buzz_count = defaultdict(int)  # track consecutive buzzes
        user_buzz_cooldown = {}  # user_id -> timestamp

        async def buzz_callback(interaction: discord.Interaction):
            user_id = interaction.user.id
            now = time.time()

            # check spam cooldown
            if user_id in user_buzz_cooldown and now - user_buzz_cooldown[user_id] < COOLDOWN_SECONDS:
                await interaction.response.send_message(
                    "⏳ Slow down! You must wait  seconds before buzzing again.", ephemeral=True)
                return

            user_buzz_count[user_id] += 1
            if user_buzz_count[user_id] > 3:
                user_buzz_cooldown[user_id] = now
                user_buzz_count[user_id] = 0
                await interaction.response.send_message(
                    f"🚫 Too many buzzes! Wait {COOLDOWN_SECONDS} seconds before pressing again.", ephemeral=True)
                return

            team = sess.team_of(interaction.user)
            if not team:
                await interaction.response.send_message("❌ You are not in this game.", ephemeral=True)
                return

            current_image = sess.flashed_images[-1]
            correct = current_image in duplicates
            line = ""

            if correct:
                if team not in sess.teams_buzzed_current:
                    sess.team_scores[team] += 1
                    sess.scores[user_id] += 1
                    sess.teams_buzzed_current.add(team)
                    sess.current_duplicate_count -= 1
                    line = f"✅ {interaction.user.display_name} buzzed +1 point"
                else:
                    line = f"❌ {interaction.user.display_name} buzzed, team already scored"
            else:
                if sess.team_scores[team] > 0:
                    sess.team_scores[team] -= 1
                    sess.scores[user_id] = max(sess.scores[user_id] - 1, 0)
                    line = f"❌ {interaction.user.display_name} buzzed -1 point"
                else:
                    line = f"❌ {interaction.user.display_name} buzzed no point"

            sess.buzz_log = [line]
            embed.set_field_at(1, name="Buzzer 🔔", value="\n".join(sess.buzz_log), inline=False)
            embed.set_field_at(2, name="Duplicates Remaining", value=str(sess.current_duplicate_count), inline=False)
            await interaction.response.edit_message(embed=embed)

        btn = Button(label="🚨 BUZZER", style=discord.ButtonStyle.danger)
        btn.callback = buzz_callback
        view.add_item(btn)
        return view

    async def show_scoreboard(self, ctx, sess, round_idx):
        embed = discord.Embed(title=f"📊 Scoreboard after Round {round_idx}", color=discord.Color.gold())
        for t in ["A", "B"]:
            members = [f"{m.mention} - {sess.scores[m.id]}pt" for m in sess.teams[t]]
            members_text = "\n".join(members) or "None"
            embed.add_field(name=f"Team {t} | Total: {sess.team_scores[t]}pt", value=members_text, inline=False)
        await ctx.send(embed=embed)

    async def end_game(self, ctx, sess):
        A, B = sess.team_scores["A"], sess.team_scores["B"]
        embed = discord.Embed(title="🏁 Game Over! Final Scores", color=discord.Color.gold())
        for t in ["A", "B"]:
            members = [f"{m.mention} - {sess.scores[m.id]}pt" for m in sess.teams[t]]
            members_text = "\n".join(members) or "None"
            embed.add_field(name=f"Team {t} | Total: {sess.team_scores[t]}pt", value=members_text, inline=False)
        await ctx.send(embed=embed)

        if A == B:
            await ctx.send(f"🤝 It's a tie! ({A} - {B})")
            self.active_session = None
            return

        winner, loser = ("A", "B") if A > B else ("B", "A")
        await ctx.send(f"🎉 Congratulations Team {winner}! You crushed it! 🏆")
        win_embed = discord.Embed(
            title=f"🏆 Team {winner} Victorious!",
            color=discord.Color.green()
        )
        win_embed.set_image(url="https://i.pinimg.com/originals/34/95/89/3495896775dff68c4a683a7994b17135.gif")
        await ctx.send(embed=win_embed)

        # Timeout losing team (skip admins)
        timeout_seconds = len(sess.flashed_images) * IMAGE_DURATION
        for member in sess.teams[loser]:
            try:
                if not member.guild_permissions.administrator:
                    await member.timeout(utcnow() + timedelta(seconds=timeout_seconds),
                                         reason="Lost Montage Challenge ❄️")

                    await asyncio.sleep(0.5)  # small pause to ensure Discord applies changes
            except Exception as e:
                print(f"Failed to timeout {member}: {e}")

        await ctx.send(f"🥶 Team {loser}, better luck next time! You are timed out for {timeout_seconds}s ❄️")
        self.active_session = None

async def setup(bot):
    await bot.add_cog(MontageChallenge(bot))
