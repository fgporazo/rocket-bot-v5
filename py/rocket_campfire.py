import discord
from discord.ext import commands, tasks
import asyncio
import random
from datetime import datetime, timedelta
from helpers import (award_points)

MAX_CAMPERS = 15
MIN_CAMPERS = 2
JOIN_COUNTDOWN = 60
CONFESS_TIMEOUT = 60  # in seconds
REACTION_COUNTDOWN = 15  # 30s to react
LIT_COOLDOWN_HOURS = 5
TIMEOUT_DURATION = 60  # 1 minute freeze for kicked players after campfire

class RocketCampfire(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.campfires = {}  # guild_id -> campfire state
        self.user_lit_timestamp = {}  # user_id -> last lit time

    async def cog_load(self):
        self.reaction_cleaner.start()

    # ----------------- CC Group -----------------
    @commands.group(name="cc", invoke_without_command=True)
    async def cc(self, ctx):
        """📖 Team Rocket Campfire Commands Guide"""
        commands_list = [
            f"`.cc {c.name}` - {c.help or 'No description'}"
            for c in self.cc.commands
        ]
        commands_list.sort()
        help_text = "\n".join(commands_list)
        await ctx.send(f"📖 **Team Rocket Campfire Commands Guide**\n{help_text}")

    # ----------------- .cc lit -----------------
    @cc.command(name="lit", help="Light the campfire.")
    async def cc_lit(self, ctx):
        now = datetime.utcnow()
        last_lit = self.user_lit_timestamp.get(ctx.author.id)
        if last_lit and (now - last_lit).total_seconds() < LIT_COOLDOWN_HOURS * 3600:
            remaining = int((LIT_COOLDOWN_HOURS*3600 - (now - last_lit).total_seconds()) / 60)
            await ctx.send(f"❌ You are on cooldown! Try again in {remaining} minutes.")
            return

        guild_id = str(ctx.guild.id)
        record = self.campfires.get(guild_id)
        if record and record["active"]:
            await ctx.send("❌ A campfire is already ongoing!")
            return

        self.user_lit_timestamp[ctx.author.id] = now
        self.campfires[guild_id] = {
            "active": True,
            "joining_phase": True,
            "campers": [ctx.author.id],
            "kicked_campers": [],
            "confessions": [],
            "confession_thread": ctx.channel.id,
            "finished": False
        }

        try:
            file = discord.File("assets/campfire.gif", filename="campfire.gif")
            embed = discord.Embed(
                description=f"🔥 {ctx.author.display_name} lit the campfire!\nJoin using `.cc join` \nMinimum Players: {MIN_CAMPERS}\nMaximum Players: {MAX_CAMPERS}\n⏳ {JOIN_COUNTDOWN}s left!",
                color=discord.Color.orange()
            )
            embed.set_image(url="attachment://campfire.gif")
            await ctx.send(embed=embed, file=file)
            await ctx.send(f"✅ {ctx.author.display_name} automatically joined the campfire! (1/{MAX_CAMPERS})")
        except:
            await ctx.send(f"🔥 {ctx.author.display_name} lit the campfire!\nJoin using `.cc join` \nMinimum Players: {MIN_CAMPERS}\nMaximum Players: {MAX_CAMPERS}\n⏳ {JOIN_COUNTDOWN}s left!")

        asyncio.create_task(self.join_countdown(ctx.guild, ctx.channel))

    # ----------------- .cc join -----------------
    @cc.command(name="join", help="Join an active campfire during the join countdown.")
    async def cc_join(self, ctx):
        guild_id = str(ctx.guild.id)
        record = self.campfires.get(guild_id)
        if not record or not record["active"]:
            await ctx.send("❌ No active campfire.")
            return
        if not record["joining_phase"]:
            await ctx.send("❌ Join phase ended!")
            return
        if ctx.author.id in record["campers"]:
            await ctx.send("❌ You already joined!")
            return

        if len(record["campers"]) >= MAX_CAMPERS:
            await ctx.send("⚠️ Sorry. Campfire full!")
            return

        record["campers"].append(ctx.author.id)
        await ctx.send(f"✅ {ctx.author.display_name} joined the campfire! ({len(record['campers'])}/{MAX_CAMPERS})")

    # ----------------- Join Countdown -----------------
    async def join_countdown(self, guild, channel):
        guild_id = str(guild.id)
        record = self.campfires[guild_id]
        remaining = JOIN_COUNTDOWN
        status_msg = await channel.send(f"⏳ Campfire join countdown: {remaining}s remaining...")

        while remaining > 0:
            await asyncio.sleep(1)
            remaining -= 1
            try:
                await status_msg.edit(content=f"⏳ Campfire join countdown: {remaining}s remaining...")
            except: pass

        record["joining_phase"] = False
        if len(record["campers"]) < MIN_CAMPERS:
            await channel.send("💀 Not enough campers! Campfire ends in failure 😭")
            record["active"] = False
            return

        await channel.send(f"🔥 The wait is over! {len(record['campers'])} campers get ready. Starting confessions...")
        asyncio.create_task(self.start_confession_loop(guild, channel))

    # ----------------- Confession Loop -----------------
    async def start_confession_loop(self, guild, channel):
        guild_id = str(guild.id)
        record = self.campfires[guild_id]
        kicked = record["kicked_campers"]
        remaining_campers = [u for u in record["campers"] if u not in kicked]
        survivors = []

        while remaining_campers:
            chosen_id = random.choice(remaining_campers)
            remaining_campers.remove(chosen_id)
            member = guild.get_member(chosen_id)
            record["current_camper"] = chosen_id

            await channel.send(f"💌 Random camper chosen! Check your DMs!")

            try:
                dm_msg = await member.send(
                    f"💌 You have been chosen to confess! You have {CONFESS_TIMEOUT}s.\n"
                    "Use `.cc confess <yes/no> <message>`\n"
                    "yes = reveal name publicly\nno = stay anonymous\n"
                    "Tip: Maximum of 500 characters only."
                )
            except:
                await channel.send(f"❌ Could not DM {member.display_name}. Skipped!")
                kicked.append(chosen_id)
                continue

            # Wait confession with retry if wrong format
            confess_success = False
            start_time = datetime.utcnow()

            while (datetime.utcnow() - start_time).total_seconds() < CONFESS_TIMEOUT:
                def check(m):
                    return m.author.id == chosen_id and m.content.lower().startswith(".cc confess")

                try:
                    dm_response = await self.bot.wait_for("message", timeout=CONFESS_TIMEOUT - (datetime.utcnow() - start_time).total_seconds(), check=check)
                except asyncio.TimeoutError:
                    await member.send("💀 Time's up! You didn't confess in time.")
                    break

                content = dm_response.content[len(".cc confess "):].strip()
                parts = content.split(" ", 1)
                if len(parts) != 2 or parts[0].lower() not in ("yes", "no") or not parts[1]:
                    await member.send("❌ Invalid format! Make sure to use `.cc confess yes/no <message>`")
                    continue  # allow retry
                anon, msg = parts
                anon = anon.lower()
                if len(msg) > 500:
                    await member.send("❌ Message too long (max 500 chars). Try again.")
                    continue

                # Valid confession
                confess_success = True
                sender_name = member.display_name if anon == "yes" else "Anonymous"
                embed = discord.Embed(
                    title="💌 Campfire Confession",
                    description=f"{msg}\n\n🔥 Campers, react 👍 or 👎 to vote!",
                    color=discord.Color.gold()
                )
                embed.set_author(name=sender_name)
                confess_msg = await channel.send(embed=embed)
                await confess_msg.add_reaction("👍")
                await confess_msg.add_reaction("👎")
                record["confessions"].append({"author_id": chosen_id, "anon": anon, "msg": confess_msg})
                await member.send(f"✅ Your confession delivered here: {confess_msg.jump_url}")
                break  # exit while loop

            if not confess_success:
                kicked.append(chosen_id)

            # Reaction countdown
            countdown_msg = await channel.send(f"⏳ 30s to react! Campers, vote 👍 or 👎!")
            for remaining in range(REACTION_COUNTDOWN, 0, -1):
                try:
                    await countdown_msg.edit(content=f"⏳ {remaining}s to react! Campers, vote 👍 or 👎!")
                except: pass
                await asyncio.sleep(1)

            # Count votes and kick if majority 👎
            msg = await channel.fetch_message(confess_msg.id)
            thumbs_up = sum(r.count - 1 for r in msg.reactions if str(r.emoji) == "👍")
            thumbs_down = sum(r.count - 1 for r in msg.reactions if str(r.emoji) == "👎")
            if thumbs_down > thumbs_up:
                kicked.append(chosen_id)
                await channel.send(f"❌ Camper got majority 👎 and will be frozen after campfire!")
            else:
                survivors.append(chosen_id)
                await channel.send(f"✅ Camper's confession passed!")

        # ----------------- Freeze all kicked players after campfire ends -----------------
        await channel.send("🔥 Campfire ended! All kicked players are frozen ❄️ and will be rewarded 3 gems 💎.")
        await channel.send("🎉 All surviving campers are rewarded with 5 gems 💎!")
        for camper in survivors:
            member = guild.get_member(camper)
            await member.send(f"🎉 Congratulations camper! You survived the campfire confession and earned bonus gems! 💎")
            await award_points(self.bot, member, 5, dm=True)

        for user_id in kicked:
            member = guild.get_member(user_id)
            if member:

                until = discord.utils.utcnow() + timedelta(seconds=TIMEOUT_DURATION)
                try:
                    await member.edit(timed_out_until=until, reason="Campfire ended - auto freeze")
                    await member.send(f"❄️ You were kicked during the campfire and are now frozen for {TIMEOUT_DURATION//60} minutes!")
                    await member.send(f"You still earned bonus gems just for joining the campfire!")
                    await award_points(self.bot, member, 3, dm=True)
                except:
                    await channel.send(f"⚠️ Could not freeze {member.display_name}.")

        record["active"] = False
        record["finished"] = True

    # ----------------- Reaction Cleaner -----------------
    @tasks.loop(seconds=2)
    async def reaction_cleaner(self):
        await self.bot.wait_until_ready()
        for guild_id, record in self.campfires.items():
            for conf in record.get("confessions", []):
                try:
                    msg = await conf["msg"].channel.fetch_message(conf["msg"].id)
                    for reaction in msg.reactions:
                        if str(reaction.emoji) not in ("👍","👎"):
                            users = await reaction.users().flatten()
                            for u in users:
                                if u != self.bot.user:
                                    await msg.remove_reaction(reaction.emoji,u)
                except: continue

async def setup(bot):
    await bot.add_cog(RocketCampfire(bot))
