# py/rocket_date_game.py
import random
import re
from datetime import date, datetime
from typing import Optional, Dict, Union, List
import os
import discord
from discord.ext import commands

from helpers import (
    ADMIN_IDS, DB_PATH,
    ADMIN_DATE_LIMIT_PER_DAY, USER_DATE_LIMIT_PER_DAY,
    init_db, is_admin, is_edate_gamer, get_gender_emoji, get_guild_contestants,
    safe_send, TextPaginator, EmbedPaginator,
    count_sent_today, insert_record, get_pending_between, update_status,
    fetch_incoming_history, load_json_file,award_points,
    update_daily_quest, DAILY_QUEST_IDS, DAILY_QUEST_CHANNEL_ID,compute_points,reset_heartthrob_role
)

# Optional constants
MEDALS = ["🥇", "🥈", "🥉"]
PROTECTED_IDS = []  # Add protected user IDs here
LEADERBOARD_CHANNEL_ID = int(os.getenv("LEADERBOARD_CHANNEL_ID", 0))

class RocketDate(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        # Load JSON files for fun commands
        self.roast_lines = load_json_file("json/roast_lines.json", [])
        self.scream_lines = load_json_file("json/scream_lines.json", [])
        self.drama_lines = load_json_file("json/drama_lines.json", [])
        self.thunderbolt_lines = load_json_file("json/thunderbolt_lines.json", [])
        self.thunderbolt_protected_lines = load_json_file("json/thunderbolt_protected_replies.json", [])

        # Queues for non-repeating lines
        self.roast_queue = self.roast_lines.copy()
        random.shuffle(self.roast_queue)
        self.scream_queue = self.scream_lines.copy()
        random.shuffle(self.scream_queue)
        self.last_scream_template = None
        self.drama_queue = self.drama_lines.copy()
        random.shuffle(self.drama_queue)
        self.last_drama_template = None
        self.thunderbolt_queue = self.thunderbolt_lines.copy()
        random.shuffle(self.thunderbolt_queue)

        # Feedback memory
        self.user_feedback_count: Dict[int, Dict[str, Union[int, Optional[date]]]] = {}
        # Role IDs
        self.choose_roles_channel_id = int(os.getenv("CHOOSE_ROLES_CHANNEL_ID"))
        self.catch_pokemen_id = int(os.getenv("CATCH_POKEMEN_ROLE_ID"))
        self.catch_pokewomen_id = int(os.getenv("CATCH_POKEWOMEN_ROLE_ID"))
        self.catch_all_id = int(os.getenv("CATCH_ALL_ROLE_ID"))

    # -------------------- MAIN GROUP --------------------
    @commands.group(name="tr", invoke_without_command=True)
    async def tr(self, ctx):
        """📖 Team Rocket Fun & Games Guide"""
        # Filter commands by name
        allowed = ["list", "date","datelb", "dateyes","dateno","history", "leaderboard", "roast","scream","drama","thunderbolt"]  # commands you want to show
        commands_list = [
            f"`.tr {c.name}` - {c.description or 'No description'}"
            for c in self.tr.commands
            if c.name in allowed
        ]
        commands_list.sort()
        help_text = "\n".join(commands_list)
        await safe_send(ctx, f"📖 **Team Rocket E-Date & Fun Commands Guide**\n{help_text}")

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.CommandOnCooldown):
            retry_after = int(error.retry_after)
            await safe_send(
                ctx,
                f"⏳ {ctx.author.mention}, slow down grunt! "
                f"Love missions recharge in **{retry_after} seconds** 💘🚀"
            )
            return
        raise error  # re-raise other errors so they're not swallowed

    @tr.command(name="quest", aliases=["q", "daily"], description="Check your daily quest progress")
    async def tr_quest(self, ctx):
        """Show daily quest progress as a single embed with checkboxes and reward claim status."""
        channel = self.bot.get_channel(DAILY_QUEST_CHANNEL_ID)
        if not channel:
            return await safe_send(ctx, "⚠️ Daily Quest channel not found!")

        today_str = str(date.today())
        latest_msg: discord.Message | None = None

        # Look for today's message
        async for msg in channel.history(limit=50):
            if msg.content.startswith(f"Daily Quest — {today_str}"):
                latest_msg = msg
                break

        # Create today's message if missing
        if not latest_msg:
            latest_msg = await channel.send(f"Daily Quest — {today_str}")

        lines = latest_msg.content.splitlines()
        user_id_str = str(ctx.author.id)
        user_line_index: int | None = None

        # Check if user line exists
        for i, line in enumerate(lines[1:], start=1):
            if user_id_str in line:
                user_line_index = i
                break

        # If missing, create user line with all zeros and NO claim
        if user_line_index is None:
            quest_status = " | ".join(f"{qid}0" for qid in DAILY_QUEST_IDS)
            lines.append(f"{ctx.author.display_name} — {user_id_str} | {quest_status} | NO")
            user_line_index = len(lines) - 1
            await latest_msg.edit(content="\n".join(lines))

        # Get full quest status string
        user_line = lines[user_line_index]
        parts = [p.strip() for p in user_line.split("|")]
        quest_status_raw = " | ".join(parts[1:1 + len(DAILY_QUEST_IDS)])  # a-d statuses
        reward_claimed = parts[-1] if len(parts) > len(DAILY_QUEST_IDS) + 1 else "NO"

        # Map quest IDs to emojis & descriptions
        quest_map = {
            "a": "⚡ Thunderbolt someone",
            "b": "🔥 Roast someone",
            "c": "🎭 Drama someone",
            "d": "📰 Press quest"
        }

        # Build the description with checkboxes
        description_lines = []
        for qid in DAILY_QUEST_IDS:
            status = "✅" if re.search(rf"{qid}1", quest_status_raw) else "⬛"
            description_lines.append(f"{status}  {quest_map[qid]}")

        # Check if all quests are done
        all_done = all(re.search(rf"{qid}1", quest_status_raw) for qid in DAILY_QUEST_IDS)
        award_gems = 100
        # Footer logic
        if reward_claimed == "YES":
            footer_text = "\n💎 You already claimed your reward. Come back tomorrow!"
        elif all_done:
            footer_text = f"\n💎 Complete all quests to earn {award_gems} gems! Resets tomorrow.\n⚡ Commands: `.tr thunderbolt` `.tr roast` `.tr drama` `.pq start`"
        else:
            footer_text = f"\n💎 Complete all quests to earn {award_gems} gems! Resets tomorrow.\n⚡ Commands: `.tr thunderbolt` `.tr roast` `.tr drama` `.pq start`"

        # Create embed
        embed = discord.Embed(
            title=f"{ctx.author.display_name}'s Daily Quests — {today_str}",
            description="\n".join(description_lines) + f"\n{footer_text}",
            color=0xFF99FF
        )

        await ctx.send(embed=embed)

        # Award gems automatically if all done and not claimed
        if all_done and reward_claimed != "YES":
            await award_points(self.bot, ctx.author, award_gems, notify_channel=ctx.channel)
            # Update user line to mark reward claimed
            lines[user_line_index] = f"{parts[0]} | {quest_status_raw} | YES"
            await latest_msg.edit(content="\n".join(lines))

    # ────────── TR LIST ──────────
    @tr.command(name="list", description="See all PokeCandidates 🚀")
    @commands.cooldown(5, 60, commands.BucketType.user)
    async def tr_list(self, ctx):
        contestants = get_guild_contestants(ctx.guild)
        if not contestants:
            return await safe_send(ctx, "⚠️ No PokeCandidates found in this server.")

        contestants.sort(key=lambda m: m.display_name.lower())

        # Define your catch role IDs
        CATCH_ROLE_IDS = {
            "Catching PokeMen": self.catch_pokemen_id,
            "Catching PokeWomen": self.catch_pokewomen_id,
            "Catching 'em all": self.catch_all_id
        }

        lines = []
        for m in contestants:
            # Find which Catching roles the member has
            member_roles = [discord.utils.get(m.guild.roles, id=rid) for name, rid in CATCH_ROLE_IDS.items() if
                            discord.utils.get(m.roles, id=rid)]
            # Convert to mentions instead of names
            role_text = ", ".join(role.mention for role in member_roles) if member_roles else ""
            lines.append(f"{get_gender_emoji(m)} {m.display_name} - {role_text}")

        page_size = 10
        embeds = []
        for i in range(0, len(lines), page_size):
            embed = discord.Embed(
                title=f"🚀 Team Rocket PokeCandidates List ({len(contestants)})",
                description="\n".join(lines[i:i + page_size]),
                color=0xFF99FF
            )
            embed.set_footer(text="✨ Who will rise to the top of Team Rocket E-Games?")
            embeds.append(embed)

        paginator = EmbedPaginator(embeds, ctx.author)
        await paginator.start(ctx)

    # -------------------- DATE REQUEST --------------------
    @tr.command(name="date", description="Send an e-date request (max 3 per day 💌)")
    @commands.cooldown(5, 60, commands.BucketType.user)
    async def tr_date(self, ctx, member: discord.Member = None):
        sender = ctx.author
        if not member:
            return await safe_send(ctx, "❌ Please mention a valid user to send a date request to.")
        if member.id == sender.id:
            return await safe_send(ctx, "❌ You cannot date yourself! 😼")

        # Role checks for participation
        if not is_edate_gamer(sender) or not is_edate_gamer(member):
            if ctx.guild.get_role(self.catch_pokemen_id):
                catchPoke = f"<@&{self.catch_pokemen_id}>"
            else:
                catchPoke = "Catching PokeMen"

            if ctx.guild.get_role(self.catch_pokewomen_id):
                catchPokeWomen = f"<@&{self.catch_pokewomen_id}>"
            else:
                catchPokeWomen = "Catching PokeWomen"

            if ctx.guild.get_role(self.catch_all_id):
                catchAll = f"<@&{self.catch_all_id}>"
            else:
                catchAll = "Catching 'em all"

            return await safe_send(
                ctx,
                f"❌ Only candidates with Catching roles can participate in e-dates. 🚀\n\n"
                f"Catching roles include: {catchPoke}, {catchPokeWomen}, {catchAll}.\n"
                f"If you're interested in e-date games, go to <#{self.choose_roles_channel_id}> "
                f"and assign yourself the Catching roles you're interested in."
            )

        # Daily limit check (no exceptions)
        limit = ADMIN_DATE_LIMIT_PER_DAY if is_admin(sender) else USER_DATE_LIMIT_PER_DAY
        sent_today = count_sent_today(ctx.guild.id, sender.id)
        if sent_today >= limit:
            return await safe_send(ctx, f"❌ Daily limit reached ({limit} per day). 💔")

        # Optional: prevent duplicate pending with the same user
        pending_id = get_pending_between(ctx.guild.id, sender.id, member.id)  # ✅ consistent usage
        if pending_id:
            return await safe_send(ctx, "❌ You already have a pending e-date with this user! 💌")

        # Record the request (pending)
        insert_record(ctx.guild.id, user_id=member.id, sender_id=sender.id)

        embed = discord.Embed(
            title="💌 E-Date Request Sent!",
            description=(
                f"{sender.mention} has requested an e-date with {member.mention}!\n\n"
                f"To accept: `.tr dateyes @{sender.display_name}`\n"
                f"To reject: `.tr dateno @{sender.display_name} <reason>`"
            ),
            color=0xFF99FF
        )
        embed.set_footer(text="🚀 Love is a battlefield, choose wisely.")
        await safe_send(ctx, embed=embed)
        # Award +1 point for using this command
        await award_points(self.bot, ctx.author, 5,notify_channel=ctx.channel)
    # -------------------- ACCEPT --------------------
    @tr.command(name="dateyes", description="Accept an e-date request from other PokeCandidates 💖")
    @commands.cooldown(5, 60, commands.BucketType.user)
    async def tr_date_yes(self, ctx, member: discord.Member):
        receiver = ctx.author
        record_id = get_pending_between(ctx.guild.id, member.id, receiver.id)  # ✅ consistent usage

        # Role checks for participation
        if not is_edate_gamer(receiver) or not is_edate_gamer(member):
            return await safe_send(ctx,
                                   f"❌ Only candidates with Catching roles can participate in e-dates. 🚀\n\n"
                                   f"Catching roles include: <@&{self.catch_pokemen_id}>, <@&{self.catch_pokewomen_id}>, <@&{self.catch_all_id}>.\n"
                                   f"If you're interested in e-date games, go to <#{self.choose_roles_channel_id}> "
                                   f"and assign yourself the Catching roles you're interested in.")

        if not record_id:
            return await safe_send(ctx, "❌ No pending request from this user! 💔")

        update_status(record_id, status='yes')

        embed = discord.Embed(
            title="💖 E-Date Accepted!",
            description=f"{receiver.mention} accepted {member.mention}'s e-date! 💘 Points awarded.",
            color=0xFF99FF
        )
        embed.set_footer(text="💘 Team Rocket spreads love and chaos!")
        await safe_send(ctx, embed=embed)

        await award_points(self.bot, ctx.author, 5, notify_channel=ctx.channel)
    # -------------------- REJECT --------------------
    @tr.command(name="dateno", description="Reject an e-date request from a user 💔 (optionally add a reason)")
    @commands.cooldown(5, 60, commands.BucketType.user)
    async def tr_date_no(self, ctx, member: discord.Member, *, reason: str = ""):
        receiver = ctx.author
        record_id = get_pending_between(ctx.guild.id, member.id, receiver.id)  # ✅ consistent usage

        # Role checks for participation
        if not is_edate_gamer(receiver) or not is_edate_gamer(member):
            return await safe_send(ctx,
                                   f"❌ Only candidates with Catching roles can participate in e-dates. 🚀\n\n"
                                   f"Catching roles include: <@&{self.catch_pokemen_id}>, <@&{self.catch_pokewomen_id}>, <@&{self.catch_all_id}>.\n"
                                   f"If you're interested in e-date games, go to <#{self.choose_roles_channel_id}> "
                                   f"and assign yourself the Catching roles you're interested in.")

        if not record_id:
            return await safe_send(ctx, "❌ No pending request from this user! 💔")

        update_status(record_id, status='no', reason=reason)

        embed = discord.Embed(
            title="💔 E-Date Rejected",
            description=(
                f"{receiver.mention} rejected {member.mention}'s e-date.\n"
                f"Reason: {reason or 'No reason provided'}"
            ),
            color=0xFF99FF
        )
        embed.set_footer(text="😼 Don’t break too many hearts, Rocket!")
        await safe_send(ctx, embed=embed)
        await award_points(self.bot, ctx.author, 3, notify_channel=ctx.channel)
    # -------------------- HISTORY --------------------
    @tr.command(name="history", description="💌 Show e-date history")
    @commands.cooldown(5, 60, commands.BucketType.user)
    async def tr_history(self, ctx, member: Optional[discord.Member] = None):
        member = member or ctx.author

        # Role checks for participation
        if not is_edate_gamer(member):
            return await safe_send(ctx,
                                   f"❌ Only candidates with Catching roles can participate in e-dates. 🚀\n\n"
                                   f"Catching roles include: <@&{self.catch_pokemen_id}>, <@&{self.catch_pokewomen_id}>, <@&{self.catch_all_id}>.\n"
                                   f"If you're interested in e-date games, go to <#{self.choose_roles_channel_id}> "
                                   f"and assign yourself the Catching roles you're interested in.")

        rows = fetch_incoming_history(ctx.guild.id, member.id)
        if not rows:
            return await safe_send(ctx, f"{member.mention} has no incoming e-date history yet! 💔")

        lines = []
        for date_str, sender_id, status, reason in rows:
            sender = ctx.guild.get_member(sender_id)
            sender_name = sender.mention if sender else f"User({sender_id})"

            # Style by status
            if status == "yes":
                line = f"{date_str} — Accepted from {sender_name} 💖"
            elif status == "no":
                reason_text = f" — Reason: {reason}" if reason else ""
                line = f"{date_str} — Rejected from {sender_name}{reason_text} 💔"
            else:  # pending
                line = f"{date_str} — Pending from {sender_name} 💌"

            lines.append(line)

        # Paginate 10 per page
        page_size = 10
        embeds = []
        for i in range(0, len(lines), page_size):
            embed = discord.Embed(
                title=f"💌 E-Date History of {member.display_name}",
                description=f"{member.mention}\n\n" + "\n".join(lines[i:i + page_size]),
                color=discord.Color.pink()
            )
            embed.set_footer(text="💌 Memories recorded in Rocket archives.")
            embeds.append(embed)

        paginator = EmbedPaginator(embeds, ctx.author)
        await paginator.start(ctx)
    # -------------------- DATE LEADERBOARD --------------------
    @tr.command(name="datelb", description="🏆 Show the e-date leaderboard")
    async def date_leaderboard(self, ctx):
        HEARTTHROB_ROLE_NAME = "Heartthrob 💘"

        # --- Compute dynamic points ---
        user_points: dict[int, int] = compute_points(ctx.guild)
        if not user_points:
            return await safe_send(ctx, "❌ No e-date activity recorded yet!")

        # --- Sort by points descending ---
        sorted_users = sorted(user_points.items(), key=lambda x: x[1], reverse=True)

        # --- Build leaderboard entries ---
        lb_entries = []
        for i, (uid, pts) in enumerate(sorted_users, start=1):
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}️⃣"
            member = ctx.guild.get_member(uid) or await ctx.guild.fetch_member(uid)
            name = member.display_name if member else str(uid)
            lb_entries.append(f"{medal} {name} — {pts} 💘")

        # --- Heartthrob role assignment ---
        top_member_id = sorted_users[0][0]  # top scorer
        role = await reset_heartthrob_role(ctx.guild, HEARTTHROB_ROLE_NAME, top_member_id)

        top_member = ctx.guild.get_member(top_member_id) or await ctx.guild.fetch_member(top_member_id)
        if top_member:
            if not role:
                role = await ctx.guild.create_role(
                    name=HEARTTHROB_ROLE_NAME,
                    colour=discord.Colour.red(),
                    reason="Top e-date scorer"
                )
            if role not in top_member.roles:
                await top_member.add_roles(role, reason="Top e-date scorer")

        # --- Random Heartthrob announcement inside embed ---
        messages = [
            f"💘 {top_member.mention} has stolen everyone’s heart and is now {role.mention}!",
            f"🏆 All hail {top_member.mention}! {role.mention} strikes again!",
            f"❤️ Look at {top_member.mention} getting all the love! {role.mention} status unlocked!",
            f"💝 {top_member.mention} just reached legendary {role.mention} level!",
            f"💌 Warning: {top_member.mention} is officially too charming—meet {role.mention}!"
        ]
        chosen_msg = random.choice(messages)

        # --- Create paginated embed ---
        embeds = [
            discord.Embed(
                title="🏆 E-Date Leaderboard",
                description="\n".join(lb_entries[i:i + 10]),
                color=discord.Color.red()
            )
            for i in range(0, len(lb_entries), 10)
        ]

        # --- Add Heartthrob announcement to first embed ---
        if embeds:
            embeds[0].add_field(name="\u200b", value=chosen_msg, inline=False)  # blank name

        # --- Pagination ---
        paginator = EmbedPaginator(embeds, ctx.author)
        await paginator.start(ctx)

    # --------------------GEMS LEADERBOARD --------------------
    @tr.command(
        name="leaderboard",
        aliases=["lb", "top"],
        description="See the Rocket E-Games Leaderboard 🚀"
    )
    async def tr_leaderboard(self, ctx):
        # --- Send initial "calculating" message ---
        calculating_msg = await ctx.send("⏳ Calculating leaderboard, please wait...")

        # --- Fetch latest leaderboard message ---
        channel = self.bot.get_channel(LEADERBOARD_CHANNEL_ID)
        if not channel:
            await calculating_msg.edit(content="⚠️ Leaderboard channel not found.")
            return

        try:
            msg = [m async for m in channel.history(limit=1, oldest_first=False)][0]
        except IndexError:
            await calculating_msg.edit(content="⚠️ No leaderboard message found.")
            return

        # --- Parse leaderboard ---
        import re
        leaderboard = []
        for line in msg.content.splitlines():
            parts = [p.strip() for p in line.split("-")]
            if len(parts) != 3:
                continue
            name, uid_str, points_str = parts
            try:
                uid = int(re.sub(r"\D", "", uid_str))
                points = int(re.sub(r"\D", "", points_str))
            except ValueError:
                continue
            leaderboard.append((name, uid, points))

        if not leaderboard:
            await calculating_msg.edit(content="⚠️ Leaderboard is empty or malformed.")
            return

        # --- Sort by points descending ---
        leaderboard.sort(key=lambda x: x[2], reverse=True)

        # --- Filter only members still in the server ---
        valid_leaderboard = []
        for name, uid, points in leaderboard:
            member = ctx.guild.get_member(uid)
            if member:  # only include members still in server
                valid_leaderboard.append((member, uid, points))

        if not valid_leaderboard:
            await calculating_msg.edit(content="⚠️ No valid members found in leaderboard.")
            return

        # --- Roles setup ---
        ELITE_ROLE_NAME = "Rocket Elites 🎖️"
        CHAMPION_ROLE_NAME = "Rocket Elite Commander 🎖️"
        champion_color = discord.Colour(0xC04040)  # dark red
        elite_color = discord.Colour(0xFF6666)  # pastel red

        champion_role = discord.utils.get(ctx.guild.roles, name=CHAMPION_ROLE_NAME)
        elite_role = discord.utils.get(ctx.guild.roles, name=ELITE_ROLE_NAME)

        if not champion_role:
            champion_role = await ctx.guild.create_role(
                name=CHAMPION_ROLE_NAME,
                colour=champion_color,
                reason="Top E-Games scorer"
            )
        if not elite_role:
            elite_role = await ctx.guild.create_role(
                name=ELITE_ROLE_NAME,
                colour=elite_color,
                reason="Top 2–10 E-Games scorers"
            )

        # --- Remove old roles ---
        for member in ctx.guild.members:
            try:
                if champion_role in member.roles:
                    await member.remove_roles(champion_role, reason="Reset Champion role")
                if elite_role in member.roles:
                    await member.remove_roles(elite_role, reason="Reset Elite role")
            except:
                pass

        # --- Assign new roles ---
        for idx, (member, uid, points) in enumerate(valid_leaderboard, start=1):
            try:
                if idx == 1:
                    await member.add_roles(champion_role, reason="Top scorer Champion")
                elif 2 <= idx <= 10:
                    await member.add_roles(elite_role, reason="Top 2–10 Elite")
            except:
                continue

        # --- Build embeds ---
        embeds = []
        page_size = 10
        MEDALS = ["🥇", "🥈", "🥉"]  # Only top 3

        for i in range(0, len(valid_leaderboard), page_size):
            embed = discord.Embed(
                title="🏆 E-Games Leaderboard",
                color=discord.Color.from_str("#1abc9c")
            )
            description_lines = []
            for idx, (member, uid, points) in enumerate(valid_leaderboard[i:i + page_size], start=i + 1):
                display_name = member.display_name if member else "Unknown User"
                if idx <= 3:
                    medal = MEDALS[idx - 1]
                    description_lines.append(f"{medal} {display_name} — {points:,} 💎")
                else:
                    description_lines.append(f"{display_name} — {points:,} 💎")

            embed.description = "\n".join(description_lines)

            # --- Champion announcement on first page ---
            if i == 0 and valid_leaderboard:
                top_member = valid_leaderboard[0][0]
                messages = [
                    f"🏆 All hail {top_member.mention}! You’ve struck first and earned the {champion_role.mention} crown!",
                    f"⚡ {top_member.mention} dominates the leaderboard and is the new {champion_role.mention}!",
                    f"💥 Watch out! {top_member.mention} just earned the {champion_role.mention} title!"
                ]
                embed.add_field(
                    name="",
                    value=random.choice(messages),
                    inline=False
                )

            embed.set_footer(text="✨ Be the #1 E-gamer in Events & Rocketverse!")
            embeds.append(embed)

        # --- Delete calculating message and send paginated embeds ---
        await calculating_msg.delete()
        paginator = EmbedPaginator(embeds, ctx.author)
        await paginator.start(ctx)

    # -------------------- FUN COMMANDS --------------------
    @tr.command(name="roast", description="Roast your enemy 🔥")
    @commands.cooldown(5, 60, commands.BucketType.user)
    async def roast(self, ctx, member: Optional[discord.Member] = None):
        if not member:
            return await safe_send(ctx, "🔥 Who’s the victim? Use `.tr roast @someone!`")
        if member.bot:
            return await safe_send(ctx, "🤖 You can’t roast a bot, silly human.")
        if member == ctx.author:
            return await safe_send(ctx, "💔 You can’t roast yourself — that’s emotional damage!")

        # ⚡ Admin protection
        if is_admin(member):
            await ctx.send(random.choice(self.thunderbolt_protected_lines).format(
                target=member.mention, name=ctx.author.mention
            ))
            return

        # 🔥 Pick unique roast line
        if not self.roast_queue:
            self.roast_queue = self.roast_lines.copy()
            random.shuffle(self.roast_queue)
        template = self.roast_queue.pop()

        await ctx.send(template.format(author=ctx.author.mention, target=member.mention))

        if not ctx.command.is_on_cooldown(ctx):
            await update_daily_quest(self.bot, ctx.author, "b")
            await award_points(self.bot, ctx.author, 1, notify_channel=ctx.channel)

    @tr.command(name="scream", description="Scream to your enemy 📢")
    @commands.cooldown(5, 60, commands.BucketType.user)
    async def scream(self, ctx, member: Optional[discord.Member] = None):
        if not member:
            return await safe_send(ctx, "📢 Who’s screaming? Use `.tr scream @user`")
        if member.bot:
            return await safe_send(ctx, "🤖 Bots don’t care about your screams!")
        if member == ctx.author:
            return await safe_send(ctx, "💀 Screaming at yourself? Seek help, villain.")

        available = [line for line in self.scream_queue if line != self.last_scream_template]
        if not available:
            self.scream_queue = self.scream_lines.copy()
            random.shuffle(self.scream_queue)
            available = self.scream_queue.copy()
        chosen = random.choice(available)
        self.last_scream_template = chosen
        self.scream_queue.remove(chosen)
        await ctx.send(chosen.format(author=ctx.author.mention, target=member.mention))

        if not ctx.command.is_on_cooldown(ctx):
            await award_points(self.bot, ctx.author, 1, notify_channel=ctx.channel)

    @tr.command(name="drama", description="Stirr some drama 🎭")
    @commands.cooldown(5, 60, commands.BucketType.user)
    async def drama(self, ctx, member: Optional[discord.Member] = None):
        if not member:
            return await safe_send(ctx, "🎭 Who’s stirring the drama? Use `.tr drama @user`")
        if member.bot:
            return await safe_send(ctx, "🤖 You can’t cause drama with bots!")
        if member == ctx.author:
            return await safe_send(ctx, "💅 You can’t start drama with yourself — that’s just journaling.")

        available = [line for line in self.drama_queue if line != self.last_drama_template]
        if not available:
            self.drama_queue = self.drama_lines.copy()
            random.shuffle(self.drama_queue)
            available = self.drama_queue.copy()
        chosen = random.choice(available)
        self.last_drama_template = chosen
        self.drama_queue.remove(chosen)
        await ctx.send(chosen.format(author=ctx.author.mention, target=member.mention))

        if not ctx.command.is_on_cooldown(ctx):
            await update_daily_quest(self.bot, ctx.author, "c")
            await award_points(self.bot, ctx.author, 1, notify_channel=ctx.channel)

    @tr.command(name="thunderbolt", description="Zap someone ⚡")
    @commands.cooldown(5, 60, commands.BucketType.user)
    async def tr_thunderbolt(self, ctx, member: Optional[discord.Member] = None):
        if not member:
            return await safe_send(ctx, "⚡ Who are we zapping? Use `.tr thunderbolt @user`")
        if member.bot:
            return await safe_send(ctx, "🤖 Bots are immune to your electricity!")
        if member == ctx.author:
            return await safe_send(ctx, "⚡ You can’t thunderbolt yourself! (Well, you *could*... but let’s not.)")

        # ⚡ Admin protection
        if is_admin(member):
            await ctx.send(random.choice(self.thunderbolt_protected_lines).format(
                target=member.mention, name=ctx.author.mention
            ))
            return

        if not self.thunderbolt_queue:
            self.thunderbolt_queue = self.thunderbolt_lines.copy()
            random.shuffle(self.thunderbolt_queue)
        template = self.thunderbolt_queue.pop()
        await ctx.send(template.format(author=ctx.author.mention, target=member.mention))

        if not ctx.command.is_on_cooldown(ctx):
            await update_daily_quest(self.bot, ctx.author, "a")
            await award_points(self.bot, ctx.author, 1, notify_channel=ctx.channel)

    # -------------------- SHOUTING SPRING --------------------
    @tr.command(name="ss", description="Shout about your day! 💦 Team Rocket is here for you 💖")
    @commands.cooldown(5, 60, commands.BucketType.user)
    async def tr_shouting_spring(self, ctx: commands.Context, *, message: str = ""):
        if not message:
            await ctx.send("Meowth says: 'You need to shout something!' 😼")
            return

        meowth_quotes = ["Aww. M here for u 😿", "Cheer up! 😼", "Stay strong! <:emoji_2:1390365231175176344>"]
        jessie_quotes = ["Shine on ✨", "You got this 💪", "Don't quit <:emoji_8:1390365873717645393>"]
        james_quotes = ["Together strong 🚀", "No worries 🌈", "Keep going 💥"]

        last_char = message[-1]
        count = sum(1 for c in reversed(message) if c == last_char)
        height = count

        fountain_lines = []
        for i in range(1, height + 1):
            line = "💦\u200B" * i
            if 2 <= i <= 3:
                line += f" — Meowth: {random.choice(meowth_quotes)}"
            elif 4 <= i <= 8:
                line += f" — Jessie: {random.choice(jessie_quotes)}"
            elif 9 <= i <= 12:
                line += f" — James: {random.choice(james_quotes)}"
            fountain_lines.append(line)

        start_msg = f"🚀 Team Rocket Shouting Spring 💦 activated! 🎶\nYou shouted {message}!"
        end_msg = '💫 Team Rocket says: "We hope this Shouting Spring 💦 lifts your spirits!"'

        await ctx.send(start_msg)
        for line in fountain_lines:
            await ctx.send(line)
        await ctx.send(end_msg)
        await award_points(self.bot, ctx.author, 1,notify_channel=ctx.channel)
    # -------------------- FEEDBACK --------------------
    @tr.command(name="feedback", description="Type **.tr feedback <message>**. DM the bot to use this feature 📩")
    @commands.dm_only()
    async def tr_feedback(self, ctx: commands.Context, *, message: Optional[str] = None):
        if ctx.guild is not None:
            await safe_send(ctx, "🚀 Meowth screeches: 'Feedback only works in DMs!' 😼")
            try:
                await ctx.message.delete()
            except (discord.Forbidden, discord.NotFound):
                pass
            return

        user_id = ctx.author.id
        today = datetime.utcnow().date()
        user_data = self.user_feedback_count.setdefault(user_id, {"count": 0, "date": None})  # ✅ prevents KeyError

        if not isinstance(user_data.get("date"), date) or user_data["date"] != today:
            user_data["count"] = 0
            user_data["date"] = today

        count = user_data.get("count", 0)
        if not isinstance(count, int):
            count = 0

        if count >= 1:
            return await safe_send(ctx, "💥 Team Rocket warns: You've already sent feedback today! 😈")

        if not message and not ctx.message.attachments:
            return await safe_send(ctx, "⚡ Meowth hisses: 'Provide a message or attach an image/GIF!'")

        if message:
            if len(message) > 500:
                return await safe_send(ctx, "💣 Jessie yells: 'Too long! 500 characters max!'")
            if re.search(r"https?://\S+|www\.\S+", message):
                return await safe_send(ctx, "🚫 James whispers: 'No links allowed!'")

        if len(ctx.message.attachments) > 1:
            return await safe_send(ctx, "🔥 Meowth screeches: 'Only 1 attachment allowed!'")

        if ctx.message.attachments:
            attachment = ctx.message.attachments[0]
            if not attachment.content_type or not any(x in attachment.content_type for x in ["image", "gif"]):
                return await safe_send(ctx, "⚡ Only images or GIFs allowed!")

        user_data["count"] = count + 1
        user_data["date"] = today
        await safe_send(ctx, f"💌 {ctx.author.mention}, your feedback blasted off to Team Rocket HQ! 🧨")

        for admin_id in ADMIN_IDS:
            admin = ctx.bot.get_user(admin_id)
            if admin:
                try:
                    embed = discord.Embed(
                        title="📩 Incoming Feedback!",
                        color=0xFF99FF
                    )
                    embed.add_field(name="👤 From", value=f"{ctx.author} ({ctx.author.id})", inline=False)
                    if message:
                        embed.add_field(name="💬 Message", value=message, inline=False)
                    if ctx.message.attachments:
                        embed.set_image(url=ctx.message.attachments[0].url)
                    await admin.send(embed=embed)
                except Exception as e:
                    print(f"Could not send feedback to {admin_id}: {e}")

    # -------------------- HELP --------------------
    @tr.command(name="help", description="📖 Show Team Rocket E-Date & Fun Guide")
    async def tr_help(self, ctx: commands.Context):
        commands_list = [f"`.tr {c.name}` - {c.description or 'No description'}"
                         for c in self.tr.commands]
        commands_list.sort()
        help_text = "\n".join(commands_list)
        await safe_send(ctx, f"📖 **Team Rocket E-Date & Fun Commands Guide**\n{help_text}")

    # -------------------- ANNOUNCE --------------------
    @tr.command(name="announce", description="📢 Send an announcement.")
    async def tr_announce(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None, *, content: str):
        if not is_admin(ctx.author):
            return await safe_send(ctx, "🚫 You don’t have permission to use this command!")

        try:
            await ctx.message.delete()
        except discord.Forbidden:
            pass

        target_channel = channel or ctx.channel
        await target_channel.send(content)
        await safe_send(ctx, f"✅ Announcement sent in {target_channel.mention}", delete_after=5)


# ────────────────────────────────────────
async def setup(bot):
    cog = RocketDate(bot)  # create instance
    await bot.add_cog(cog)  # register it

    # now you can safely access it
    if "feedback" in cog.tr.all_commands:
        cog.tr.all_commands["feedback"].checks = []
