from __future__ import annotations
import asyncio
import random
import re
import os
import json
from typing import Optional, Dict, Tuple, List, Union

import discord
from discord import Interaction, Message
from discord.ext import commands
from discord.ui import View, Button

from helpers import get_guild_contestants, dm_link

# ========= CONFIG =========
MYSTERY_CHANNEL_ID: int = int(os.getenv("MYSTERY_CHANNEL_ID", 0))
ROCKET_BOT_CHANNEL_ID: int = int(os.getenv("ROCKET_BOT_CHANNEL_ID", 0))
ADMIN_MYSTERY_CHANNEL_ID: int = int(os.getenv("ADMIN_MYSTERY_CHANNEL_ID", 0))

READY_TIMEOUT: int = 30
ACCEPT_TIMEOUT: int = 60
BUTTON_TIMEOUT: int = 30
CUSTOM_Q_TIMEOUT: int = 30
ANSWER_TIMEOUT: int = 60
TOTAL_ROUNDS: int = 10

UserLike = Union[discord.User, discord.Member]

# ========= HELPERS =========
def has_any_role(member: discord.Member, role_names: set[str]) -> bool:
    return bool({r.name for r in member.roles} & role_names)

async def fetch_questions_and_codes(bot: commands.Bot) -> tuple[list[str], list[str]]:
    channel = bot.get_channel(ADMIN_MYSTERY_CHANNEL_ID)
    if not channel:
        raise ValueError(f"Admin mystery channel {ADMIN_MYSTERY_CHANNEL_ID} not found!")

    messages = [m async for m in channel.history(limit=20)]
    json_msg = next((m for m in messages if m.attachments), None)
    if not json_msg:
        raise ValueError("No JSON file found in the admin channel!")

    attachment = json_msg.attachments[0]
    data_bytes = await attachment.read()
    data = json.loads(data_bytes.decode())

    questions = data.get("questions")
    codes = data.get("codenames")

    if not questions or not codes:
        raise ValueError("JSON must contain both 'questions' and 'codenames' arrays.")

    return questions, codes

def pick_questions(bank: List[str], needed: int) -> List[str]:
    if not bank:
        return ["(No question found — please add questions to the JSON!)"] * needed
    if len(bank) >= needed:
        return random.sample(bank, needed)
    chosen = random.sample(bank, len(bank))
    while len(chosen) < needed:
        chosen.append(random.choice(bank))
    return chosen

def validate_custom_question(text: str) -> bool:
    if len(text.split()) > 100:
        return False
    if re.search(r"(https?://|\[|\]|\.exe|\.zip)", text):
        return False
    return True

async def try_dm(user: UserLike, content: str, *, view: Optional[View] = None) -> Optional[discord.Message]:
    try:
        if view:
            return await user.send(content, view=view)
        return await user.send(content)
    except discord.Forbidden:
        return None

async def live_countdown(msg: discord.Message, template: str, total_seconds: int, interval: int = 1, stop_check: Optional[callable] = None):
    for i in range(total_seconds, 0, -interval):
        if stop_check and stop_check():
            break
        try:
            await msg.edit(content=template.format(i=i))
            await asyncio.sleep(interval)
        except (discord.NotFound, discord.HTTPException):
            break

# ========= COG =========
class MysteryDate(commands.Cog):
    """Cog for running Mystery Date game with Team Rocket flair."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.ongoing_dates: Dict[int, bool] = {}
        self.thread_counters: Dict[Tuple[int, str], int] = {}

        # Role IDs
        self.choose_roles_channel_id = int(os.getenv("CHOOSE_ROLES_CHANNEL_ID"))
        self.catch_pokemen_id = int(os.getenv("CATCH_POKEMEN_ROLE_ID"))
        self.catch_pokewomen_id = int(os.getenv("CATCH_POKEWOMEN_ROLE_ID"))
        self.catch_all_id = int(os.getenv("CATCH_ALL_ROLE_ID"))

    @commands.command(name="md")
    async def md_start(self, ctx: commands.Context, action: Optional[str] = None) -> Message | None:
        guild = ctx.guild
        if not guild:
            return

        if ctx.channel.id != MYSTERY_CHANNEL_ID:
            rocket_channel = guild.get_channel(ROCKET_BOT_CHANNEL_ID)
            await ctx.send(
                f"❌ You can only start a Mystery Date in <#{MYSTERY_CHANNEL_ID}>! "
                f"Go to {rocket_channel.mention if rocket_channel else f'<#{ROCKET_BOT_CHANNEL_ID}>'} and click **Mystery Date**."
            )
            return

        if action != "start":
            await ctx.send("❌ Wrong usage! Use `.md start` to begin a Mystery Date.")
            return

        # Check if author has Catching roles
        if not has_any_role(ctx.author, {"Catching PokeMen", "Catching PokeWomen", "Catching 'em all"}):
            return await ctx.send(
                f"❌ Only candidates with Catching roles can participate in e-dates. 🚀\n\n"
                f"Catching roles include: <@&{self.catch_pokemen_id}>, <@&{self.catch_pokewomen_id}>, <@&{self.catch_all_id}>.\n"
                f"If you're interested in e-date games, go to <#{self.choose_roles_channel_id}> "
                f"and assign yourself the Catching roles you're interested in.")

        guild_id = guild.id
        if self.ongoing_dates.get(guild_id, False):
            await ctx.send(
                "⛔ A Mystery Date is already running in this server — wait for it to finish! <:emoji_5:1390365446292635658>"
            )
            return

        self.ongoing_dates[guild_id] = True
        try:
            # ----- FETCH QUESTIONS & CODES -----
            QUESTIONS, CODE_NAMES = await fetch_questions_and_codes(self.bot)

            guild_contestants = get_guild_contestants(guild)
            if not guild_contestants:
                await ctx.send(
                    "🚫 No contestants registered in this server. Nobody to mystery-date! <:emoji_8:1390365873717645393>"
                )
                return

            player1: UserLike = ctx.author
            player1_code = random.choice(CODE_NAMES)

            # ----- READY PHASE -----
            class ReadyView(View):
                def __init__(self, owner: UserLike):
                    super().__init__(timeout=READY_TIMEOUT)
                    self.owner = owner
                    self.ready = False

                @discord.ui.button(label="I'm ready!", style=discord.ButtonStyle.success)
                async def ready_button(self, interaction: Interaction, button: Button):
                    if interaction.user.id != self.owner.id:
                        await interaction.response.send_message("🙅 Not for you!", ephemeral=True)
                        return
                    self.ready = True
                    await interaction.response.send_message(
                        f"\n🎩 Excellent! Team Rocket prepares your grand entrance!"
                        f"\n🎲 Picking a random PokeCandidate from the server... 💫"
                        f"\n⏳ Now we wait to see if they **accept** 💘 or **reject** ❌ the mystery date!",ephemeral=True
                    )
                    self.stop()

            ready_view = ReadyView(player1)
            dm_ok = await try_dm(
                player1,
                f"🌟 Greetings, {getattr(player1, 'display_name', player1.name)}!\n"
                f"Your undercover codename is **{player1_code}**.\n"
                f"Team Rocket will pick a random PokeCandidate from the server to join your Mystery Date! 🎯\n"
                f"Press **I'm ready** in the next **{READY_TIMEOUT} seconds**, or Team Rocket blasts off without you!",
                view=ready_view
            )
            if not dm_ok:
                await ctx.send(f"❗ {player1.mention}, open your DMs or Team Rocket can't contact you!")
                return

            await ready_view.wait()
            if not ready_view.ready:
                await try_dm(player1, "💤 You snoozed on the ready button. Mission aborted.")
                return

            # ----- THREAD CREATION -----
            mystery_channel = self.bot.get_channel(MYSTERY_CHANNEL_ID)
            if not isinstance(mystery_channel, (discord.TextChannel, discord.ForumChannel)):
                await ctx.send("❗ Mystery Date channel not found or wrong type.")
                return

            existing_threads = getattr(mystery_channel, "threads", [])
            base_name = f"Mystery Date - {player1_code}"
            counter_key = (guild_id, player1_code)
            next_idx = self.thread_counters.get(counter_key, 1)

            def is_name_taken(name: str) -> bool:
                return any(t.name == name for t in existing_threads)

            # Thread naming optimized
            thread_name = base_name
            if is_name_taken(thread_name):
                idx = next_idx
                while is_name_taken(f"{base_name} {idx}"):
                    idx += 1
                thread_name = f"{base_name} {idx}"
                next_idx = idx + 1
            else:
                next_idx += 1
            self.thread_counters[counter_key] = next_idx

            starter_msg = (
                "🚀 **Team Rocket Transmission:** A bold contestant has stepped into the arena! "
                "<:emoji_23:1391121825756483584>\n"
                f"Codename: **{player1_code}** — shrouded in mystery and ready for mischief <:emoji_18:1390721371700461578>.\n"
                "Who dares to approach? Team Rocket is watching closely... <:emoji_10:1390366675437883452>"
            )
            if isinstance(mystery_channel, discord.ForumChannel):
                thread_post = await mystery_channel.create_thread(
                    name=thread_name,
                    content=starter_msg,
                    reason=f"Mystery Date started by {player1} ({player1.id})"
                )
                thread = thread_post
            else:
                announce_msg = await mystery_channel.send(starter_msg)
                thread = await announce_msg.create_thread(name=thread_name)

            link_text = dm_link(thread)
            await try_dm(player1, f"🌌 The Mystery Date is live! Jump in: {link_text}")

            # ----- SELECT PLAYER 2 -----
            eligible_members = [m for m in guild_contestants if m.id != player1.id]
            player1_roles = {r.name for r in player1.roles}

            if "Catching PokeMen" in player1_roles:
                eligible_members = [m for m in eligible_members if has_any_role(m, {"Rocket PokeMan ♂️"})]
            elif "Catching PokeWomen" in player1_roles:
                eligible_members = [m for m in eligible_members if has_any_role(m, {"Rocket PokeWoman ♀️"})]

            if not eligible_members:
                await thread.send("🚫 No eligible compatible contestants found. Mission aborted!")
                return

            player2 = random.choice(eligible_members)
            player2_code = random.choice([n for n in CODE_NAMES if n != player1_code] or [f"{player1_code}-2"])

            # ----- ACCEPT/DECLINE -----
            class AcceptView(View):
                def __init__(self, target: UserLike, link: str):
                    super().__init__(timeout=ACCEPT_TIMEOUT)
                    self.target = target
                    self.accepted: Optional[bool] = None
                    self.link = link

                @discord.ui.button(label="Accept! 💘", style=discord.ButtonStyle.success)
                async def accept(self, interaction: Interaction, button: Button):
                    if interaction.user.id != self.target.id:
                        await interaction.response.send_message("🚫 Not for you!", ephemeral=True)
                        return
                    self.accepted = True
                    await interaction.response.send_message(f"💖 You accepted! Head to {self.link}", ephemeral=True)
                    self.stop()

                @discord.ui.button(label="Decline ❌", style=discord.ButtonStyle.danger)
                async def decline(self, interaction: Interaction, button: Button):
                    if interaction.user.id != self.target.id:
                        await interaction.response.send_message("🚫 Not for you!", ephemeral=True)
                        return
                    self.accepted = False
                    await interaction.response.send_message("💔 You declined. Cold as Ice Beam!", ephemeral=True)
                    self.stop()

            accept_view = AcceptView(player2, link_text)
            dm_ok_2 = await try_dm(
                player2,
                f"🚨 Hello {getattr(player2, 'display_name', player2.name)}!\n"
                f"A mysterious stranger **{player1_code}** requests a date.\n"
                f"Your undercover alias: **{player2_code}**.\n"
                f"Click to **Accept** or **Decline** (you have {ACCEPT_TIMEOUT} seconds):\n{link_text}",
                view=accept_view
            )
            if not dm_ok_2:
                await thread.send("❌ Couldn’t DM the chosen partner. Mission aborted. <:emoji_8:1390365873717645393>")
                return

            await accept_view.wait()
            if accept_view.accepted is None:
                await try_dm(player1, f"⏳ {player2_code} didn't reply. Mission failed.\n\n{link_text}")
                await thread.send(
                    f"⏳ {player2_code} never responded. Mystery Date cancelled. <:emoji_8:1390365873717645393>"
                )
                return
            if not accept_view.accepted:
                await try_dm(player1, f"💔 {player2_code} declined your date.\n\n{link_text}")
                await thread.send(
                    f"💔 {player2_code} iced {player1_code}. Mission canceled. <:emoji_8:1390365873717645393>"
                )
                return

            # ----- Q&A ROUNDS -----
            qa_questions = pick_questions(QUESTIONS, TOTAL_ROUNDS)
            roster: List[Tuple[UserLike, str, UserLike, str, str]] = []
            for i in range(TOTAL_ROUNDS):
                if i % 2 == 0:
                    roster.append((player1, player1_code, player2, player2_code, qa_questions[i]))
                else:
                    roster.append((player2, player2_code, player1, player1_code, qa_questions[i]))

            for round_num, (asker, asker_code, answerer, answerer_code, default_q) in enumerate(roster, start=1):
                class QChoiceView(View):
                    def __init__(self, owner: UserLike):
                        super().__init__(timeout=BUTTON_TIMEOUT)
                        self.owner = owner
                        self.choice: Optional[str] = None

                    @discord.ui.button(label="Let Team Rocket Help 💫", style=discord.ButtonStyle.primary)
                    async def random_button(self, interaction: Interaction, button: Button):
                        if interaction.user.id != self.owner.id:
                            await interaction.response.send_message("🙅 Not for you!", ephemeral=True)
                            return
                        self.choice = "random"
                        await interaction.response.send_message(
                            f"💫 Team Rocket helped you pick a random question and successfully delivered it to **{answerer_code}**!\n"
                            "Now we wait for their answer — and for their turn to challenge you with a question! 🚀",
                            ephemeral=True
                        )
                        self.stop()

                    @discord.ui.button(label="Create Custom Mischief Question ✏️", style=discord.ButtonStyle.secondary)
                    async def custom_button(self, interaction: Interaction, button: Button):
                        if interaction.user.id != self.owner.id:
                            await interaction.response.send_message("🙅 Not for you!", ephemeral=True)
                            return
                        self.choice = "custom"
                        await interaction.response.send_message(
                            "✏️ You chose to write a custom question! Type your question here in this DM (max 100 words, no links/files).",
                            ephemeral=True
                        )
                        self.stop()

                q_view = QChoiceView(asker)
                if round_num == 1:
                    await thread.send(
                        f"💘 **{answerer_code}** has accepted the Mystery Date challenge! "
                        f"{asker_code} and {answerer_code} are ready to play!"
                    )
                    dm_content = (
                        f"<:emoji_16:1390721239902847037> **Round 1**\n"
                        f"A random PokeCandidate accepted your Mystery Date challenge! 💘\n"
                        f"The PokeCandidate's alias is **{answerer_code}** 🎭\n"
                        f"Now, let's get ready for the first round!\n\n"
                        f"Choose a question method for {answerer_code}.\n"
                        f"⏳ You have {BUTTON_TIMEOUT} seconds!\n"
                        f"{dm_link(thread)}"
                    )
                else:
                    dm_content = (
                        f"\n<:emoji_16:1390721239902847037> **Round {round_num}**\n"
                        f"Choose a question method for {answerer_code}.\n"
                        f"⏳ You have {BUTTON_TIMEOUT} seconds!\n"
                        f"{dm_link(thread)}"
                    )

                dm_msg = await try_dm(asker, dm_content, view=q_view)
                if not dm_msg:
                    await thread.send(f"🚨 Could not DM **{asker_code}**. Ending the game.")
                    return

                # Countdown wait for choice
                for _ in range(BUTTON_TIMEOUT):
                    if q_view.choice:
                        break
                    await asyncio.sleep(1)

                if not q_view.choice:
                    await try_dm(asker, f"⏳ Time expired. Mission aborted! 😢\n{dm_link(thread)}")
                    await thread.send(
                        f"⏳ **{asker_code}** failed to deliver a question for {answerer_code} 😢. Team Rocket ends the Mystery Date."
                    )
                    return

                # ----- DETERMINE QUESTION -----
                if q_view.choice == "random":
                    question = default_q
                else:  # custom
                    question_submitted = None
                    try:
                        msg = await self.bot.wait_for(
                            "message",
                            check=lambda m: m.author.id == asker.id and isinstance(m.channel, discord.DMChannel),
                            timeout=CUSTOM_Q_TIMEOUT
                        )
                        if validate_custom_question(msg.content):
                            question_submitted = msg.content
                        else:
                            question_submitted = default_q
                    except asyncio.TimeoutError:
                        question_submitted = default_q
                    question = question_submitted
                    await try_dm(asker, f"💌 Your custom message has been delivered to **{answerer_code}**!"
                                        f"\nNow we wait for their answer — and for their turn to challenge you with a question! 🚀")

                # Send to answerer
                await try_dm(answerer, f"❓ Answer this question (Type your answer here):\n{question}\n{dm_link(thread)}")
                try:
                    msg = await self.bot.wait_for(
                        "message",
                        check=lambda m: m.author.id == answerer.id and isinstance(m.channel, discord.DMChannel),
                        timeout=ANSWER_TIMEOUT
                    )
                    answer = msg.content
                except asyncio.TimeoutError:
                    answer = "⏳ No answer submitted in time."

                # Also post question to thread
                await thread.send(f"❓ **{asker_code}** asks **{answerer_code}**: {question}")
                await thread.send(f"💬 **{answerer_code}** answered: {answer}")

            # ----- REVEAL PHASE -----
            class RevealView(View):
                def __init__(self, target_user: UserLike):
                    super().__init__(timeout=30)
                    self.choice: Optional[bool] = None
                    self.target_user = target_user

                @discord.ui.button(label="Yes, Reveal! 🔓", style=discord.ButtonStyle.success)
                async def yes(self, interaction: Interaction, button: Button):
                    if interaction.user.id != self.target_user.id:
                        await interaction.response.send_message("🙅 Not your button!", ephemeral=True)
                        return
                    self.choice = True
                    await interaction.response.send_message("🎭 You chose to unmask!", ephemeral=True)
                    self.stop()

                @discord.ui.button(label="No, Keep Mystery", style=discord.ButtonStyle.secondary)
                async def no(self, interaction: Interaction, button: Button):
                    if interaction.user.id != self.target_user.id:
                        await interaction.response.send_message("🙅 Not your button!", ephemeral=True)
                        return
                    self.choice = False
                    await interaction.response.send_message("🤫 Mystery lives on!", ephemeral=True)
                    self.stop()

            p1_view = RevealView(player1)
            p2_view = RevealView(player2)
            await try_dm(player1, f"{player1_code}, reveal yourself or keep the mystery alive! {dm_link(thread)}", view=p1_view)
            await try_dm(player2, f"{player2_code}, reveal yourself or keep the mystery alive! {dm_link(thread)}", view=p2_view)

            async def wait_choice(v: RevealView) -> Optional[bool]:
                try:
                    await v.wait()
                except Exception:
                    pass
                return v.choice

            c1_task = asyncio.create_task(wait_choice(p1_view))
            c2_task = asyncio.create_task(wait_choice(p2_view))
            try:
                c1, c2 = await asyncio.wait_for(asyncio.gather(c1_task, c2_task), timeout=30)
            except asyncio.TimeoutError:
                c1 = p1_view.choice
                c2 = p2_view.choice

            if c1 and c2:
                await thread.send(
                    f"<:emoji_1:1390365154310361168> **DOUBLE REVEAL!**\n"
                    f"{player1_code} is really {player1.mention}, and {player2_code} is really {player2.mention}!\n"
                    f"<:emoji_23:1391121825756483584> Team Rocket’s spying skills strike again!"
                )
            else:
                await thread.send(
                    "<:emoji_18:1390721371700461578> Mystery remains… one or both players kept their masks on. Team Rocket enjoys the drama! <:emoji_10:1390366675437883452>"
                )

        except Exception as e:
            await ctx.send(f"⚠️ An error occurred during the Mystery Date: {e}")
        finally:
            self.ongoing_dates[guild_id] = False

# ========= SETUP =========
async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MysteryDate(bot))
