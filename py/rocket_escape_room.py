import discord
from discord.ext import commands
import json
import asyncio
import random
import os
import datetime

class RocketEscapeRoom(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_rooms = {}  # {guild_id: {...}}
        self.testing_mode = True  # Set True for single-player testing
        # Get channel ID from env variable
        self.escape_story_channel_id = int(os.getenv("ADMIN_ESCAPE_STORY_CHANNEL_ID", 0))
        self.join_countdown = 60
    # ----------------- Commands -----------------
    @commands.group(name="er", invoke_without_command=True)
    async def er(self, ctx):
        """📖 Team Rocket Escape Room Commands Guide"""
        commands_list = [
            f"`.er {e.name}` - {e.help or 'No description'}"
            for e in self.er.commands
        ]
        commands_list.sort()
        help_text = "\n".join(commands_list)
        await ctx.send(f"📖 **Team Rocket Escape Room Commands Guide**\n{help_text}")

    @er.command(name="start",help="Start a dramatic Team Rocket escape mission")
    async def er_start(self, ctx):
        guild_id = ctx.guild.id
        if guild_id in self.active_rooms:
            return await ctx.send("🚨 An escape game is already in progress!")

        story = await self.fetch_latest_story()
        if not story or not story.get("escape_stories"):
            return await ctx.send("❌ No escape stories found in the channel!")

        story = random.choice(story["escape_stories"])
        min_p = story.get("min_players", 1)
        max_p = story.get("max_players", 15)

        # Initialize the room
        self.active_rooms[guild_id] = {
            "players": set(),
            "story": story,
            "puzzle_index": 0,
            "in_progress": False
        }

        # --- AUTO-JOIN the author ---
        self.active_rooms[guild_id]["players"].add(ctx.author.id)
        trapped_role = discord.utils.get(ctx.guild.roles, name="Trapped")
        pokecandidate_role = discord.utils.get(ctx.guild.roles, name="PokeCandidates")
        if trapped_role:
            await ctx.author.add_roles(trapped_role, reason="Started escape mission")
        if pokecandidate_role:
            await ctx.author.remove_roles(pokecandidate_role)

        intro = story["intro"]
        embed = discord.Embed(
            title=f"🔒 {story.get('escape_story_title')}",
            description=intro["description"],
            color=discord.Color.red()
        )
        if intro.get("img"):
            embed.set_thumbnail(url=intro["img"])
        await ctx.send(embed=embed)
        await ctx.send(f"👥 Minimum Players: {min_p} | Maximum Players: {max_p}")

        wait_msg = await ctx.send(
            f"Type `.er join` to join the escape mission! Waiting {self.join_countdown} seconds for players... ⏳"
        )

        countdown = self.join_countdown
        for i in range(countdown, 0, -1):
            await wait_msg.edit(
                content=f"Type `.er join` to join the escape mission! Waiting {i} seconds for players... ⏳"
            )
            await asyncio.sleep(1)
            if len(self.active_rooms[guild_id]["players"]) >= max_p:
                await ctx.send(f"👥 Maximum players ({max_p}) reached! Starting the mission early!")
                break

        current_players = len(self.active_rooms[guild_id]["players"])
        if current_players < min_p:
            await ctx.send("💀 Not enough players joined. Escape mission canceled!")
            for pid in self.active_rooms[guild_id]["players"]:
                member = ctx.guild.get_member(pid)
                if member and trapped_role and trapped_role in member.roles:
                    await member.remove_roles(trapped_role, reason="Mission canceled - not enough players")
                    await member.add_roles(trapped_role)
            del self.active_rooms[guild_id]
            return

        self.active_rooms[guild_id]["in_progress"] = True
        await ctx.send(f"🚀 The escape mission begins NOW with {current_players} players!")
        await self.run_puzzles(ctx, guild_id)

    @er.command(name="join",help="Join the escape crew and survive together")
    async def er_join(self, ctx):
        guild_id = ctx.guild.id
        if guild_id not in self.active_rooms:
            return await ctx.send("❌ No escape room is running! Start one with `.er start`.")

        room = self.active_rooms[guild_id]
        if room["in_progress"]:
            return await ctx.send("❌ Escape mission already in progress. You cannot join now!")

        player = ctx.author
        if player.id in room["players"]:
            return await ctx.send(f"{player.mention}, you already joined!")

        max_p = room["story"].get("max_players", 15)
        if len(room["players"]) >= max_p:
            return await ctx.send("❌ Maximum players reached. Cannot join.")

        room["players"].add(player.id)

        trapped_role = discord.utils.get(ctx.guild.roles, name="Trapped")
        pokecandidate_role = discord.utils.get(ctx.guild.roles, name="PokeCandidates")
        if trapped_role:
            await player.add_roles(trapped_role, reason="Joined escape mission")
        if pokecandidate_role:
            await player.remove_roles(pokecandidate_role)
        await ctx.send(f"✅ {player.mention} joined the escape crew! ({len(room['players'])} players now)")

    # ----------------- Fetch latest JSON from channel -----------------
    async def fetch_latest_story(self):
        if not self.escape_story_channel_id:
            return None
        channel = self.bot.get_channel(self.escape_story_channel_id)
        if not channel:
            return None
        try:
            async for msg in channel.history(limit=50):
                for att in msg.attachments:
                    if att.filename.endswith(".json"):
                        content = await att.read()
                        return json.loads(content.decode("utf-8"))
        except Exception as e:
            print(f"[ERROR] fetch_latest_story: {e}")
        return None

    # ----------------- Puzzle logic -----------------
    async def run_puzzles(self, ctx, guild_id):
        room = self.active_rooms[guild_id]
        story = room["story"]
        puzzles = story["puzzles"]
        guild = ctx.guild
        trapped_role = discord.utils.get(guild.roles, name="Trapped")
        pokecandidate_role = discord.utils.get(guild.roles, name="PokeCandidates")
        # Get all player Member objects
        players = []
        for pid in room["players"]:
            member = guild.get_member(pid)
            if not member:
                try:
                    member = await guild.fetch_member(pid)
                except discord.NotFound:
                    continue
            players.append(member)

        for puzzle in puzzles:
            embed = discord.Embed(
                title=puzzle["puzzle_title"],
                description=puzzle["description"],
                color=discord.Color.orange()
            )
            if puzzle.get("image"):
                embed.set_thumbnail(url=puzzle["image"])

            view = VoteView(self.bot, puzzle, players)
            msg = await ctx.send(embed=embed, view=view)

            countdown = puzzle.get("countdown", 30)
            for i in range(countdown, 0, -1):
                await msg.edit(content=f"⏳ Time left: {i} seconds", embed=embed)
                await asyncio.sleep(1)
                if len(view.votes) >= len(players):
                    break

            correct = await view.end_voting(ctx, message=msg)
            if not correct:
                fail_mentions = [p.mention for p in players if p]
                for p in players:
                    if p and trapped_role and trapped_role in p.roles:
                        try:
                            await p.remove_roles(trapped_role, reason="Failed escape mission")
                            await p.add_roles(pokecandidate_role)
                        except:
                            pass
                for p in players:
                    if p and (not p.guild_permissions.administrator or self.testing_mode):
                        try:
                            await self.freeze_player(ctx, p, duration=300)  # 5 minutes
                        except:
                            pass
                await ctx.send(f"Game ended. 💥 \n {', '.join(fail_mentions)} have been frozen for 5 minutes! ❄️ Team Rocket laughs maniacally!")
                if guild_id in self.active_rooms:
                    del self.active_rooms[guild_id]
                return

        for p in players:
            if p and trapped_role and trapped_role in p.roles:
                try:
                    await p.remove_roles(trapped_role, reason="Escape mission success")
                    await p.add_roles(pokecandidate_role)
                except:
                    pass

        member_mentions = [m.mention for m in players if m]
        await ctx.send(
            f"🌟 **VICTORY!** Excellent work, {', '.join(member_mentions)}, flawless escape! 🎉 "
            "Team Rocket blasts off 🚀, and no one got frozen! ❄️✨"
        )
        victory_img = story.get("victory_img")
        if victory_img:
            await ctx.send(embed=discord.Embed(title="🎉 Victory!", color=discord.Color.green()).set_thumbnail(url=victory_img))

        if guild_id in self.active_rooms:
            del self.active_rooms[guild_id]

    # ----------------- Ghosty-style timeout -----------------
    async def freeze_player(self, ctx, member: discord.Member, duration: int = 300):
        until = discord.utils.utcnow() + datetime.timedelta(seconds=duration)
        await member.edit(timed_out_until=until, reason="Failed escape mission")
        try:
            await member.send(f"💥 You are frozen for {duration // 60} minutes! Team Rocket punishes you ❄️")
        except:
            pass
        channel = discord.utils.get(ctx.guild.text_channels, name="freeze-status")
        if channel:
            await channel.send(f"❄️ {member.mention} has been frozen for {duration // 60} minutes!")

# ----------------- Voting system -----------------
class VoteView(discord.ui.View):
    def __init__(self, bot, puzzle, players):
        super().__init__(timeout=None)
        self.bot = bot
        self.puzzle = puzzle
        self.players: list[discord.Member] = players
        self.votes: dict[discord.Member, str] = {}

        for answer in puzzle.get("answers", []):
            self.add_item(VoteButton(label=answer["text"], view=self))

    async def end_voting(self, ctx, message=None) -> bool:
        self.clear_items()
        if message:
            await message.edit(view=self)

        await ctx.send("🛑 Voting ended. Results:")
        tally: dict[str, int] = {}

        for user, choice in self.votes.items():
            tally[choice] = tally.get(choice, 0) + 1
            await ctx.send(f"{user.mention} voted **{choice}**")

        if not tally:
            await ctx.send("💀 No votes cast. Team Rocket fails!")
            return False

        final_answer: str | None = max(tally, key=tally.get, default=None)
        await ctx.send(f"🏆 Team's final answer: **{final_answer}**")

        correct_answer = next((a["text"] for a in self.puzzle["answers"] if a["correct"]), None)
        if final_answer == correct_answer:
            await ctx.send(f"✅ Correct!")
            return True
        else:
            await ctx.send(f"💥 Wrong answer!")
            return False

class VoteButton(discord.ui.Button):
    def __init__(self, label, view):
        super().__init__(label=label, style=discord.ButtonStyle.primary)
        self.vote_view = view

    async def callback(self, interaction: discord.Interaction):
        if interaction.user not in self.vote_view.players:
            return await interaction.response.send_message("You're not part of this escape!", ephemeral=True)
        self.vote_view.votes[interaction.user] = self.label
        await interaction.response.send_message(f"🗳️ You voted for **{self.label}**!", ephemeral=True)

# ----------------- Cog setup -----------------
async def setup(bot):
    await bot.add_cog(RocketEscapeRoom(bot))
