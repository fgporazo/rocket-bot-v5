# rocket_dial.py
import discord
from discord.ext import commands
import asyncio
import random
from typing import Dict, Optional, Tuple, Any
import datetime
import os

# ---------------------------
# Pokémon GIFs (kept exactly as you provided)
# ---------------------------
POKEMON_GIFS = [
    {"name": "Pikachu", "url": "https://i.pinimg.com/originals/8a/81/ec/8a81ecd8fdd266b3221da325875c0ea8.gif"},
    {"name": "Eevee", "url": "https://media.tenor.com/rcvI6iu2HrYAAAAM/pokemon-eevee-eevee.gif"},
    {"name": "Charmander", "url": "https://media.tenor.com/qIhgj8cLz9UAAAAM/charmander-charmander-pokemon.gif"},
    {"name": "Squirtle", "url": "https://i.pinimg.com/originals/30/e0/04/30e0046d1ac67d128f01fdc7d7758b03.gif"},
    {"name": "Bulbasaur", "url": "https://media.tenor.com/M07Tm-PbhRkAAAAM/bulbasaur-happy.gif"},
    {"name": "Jigglypuff", "url": "https://media.tenor.com/Wmi416Of3HMAAAAM/jigglypuff-pokemon.gif"},
    {"name": "Psyduck", "url": "https://media.tenor.com/bSLB5jGlV7EAAAAM/gasp-shock.gif"},
    {"name": "Snorlax", "url": "https://media.tenor.com/NvKlIRfuoiYAAAAM/snorlax-laborday.gif"},
    {"name": "Meowth", "url": "https://media.tenor.com/ARc0RsG0saIAAAAM/pokemon-pok%C3%A9mon.gif"},
    {"name": "Gengar", "url": "https://media.tenor.com/_10HmeCFIYwAAAAM/gengar.gif"},
    {"name": "Vulpix", "url": "https://media.tenor.com/S0COAO1lCgIAAAAM/pokemon-vulpix.gif"},
    {"name": "Togepi", "url": "https://media.tenor.com/bFgGZJZBo5cAAAAM/pokemon-pok%C3%A9mon.gif"},
    {"name": "Lucario", "url": "https://i.pinimg.com/originals/16/5a/85/165a85e6ddfc14b31782a01ab29406bd.gif"},
    {"name": "Rowlet", "url": "https://media.tenor.com/R4vIJBqFUdcAAAAM/rowlet-sleep.gif"},
    {"name": "Piplup", "url": "https://media.tenor.com/9ma9Fm8PGO8AAAAM/piplup-excited.gif"},
    {"name": "Chikorita", "url": "https://media.tenor.com/OVk23Lq9ACsAAAAM/chikorita-pokemon.gif"},
    {"name": "Cubone", "url": "https://media.tenor.com/w3hoF6CcGikAAAAM/pokemon-cubone.gif"},
    {"name": "Slowpoke", "url": "https://media.tenor.com/MTnIZZmt72sAAAAM/slowpoke-pokemon.gif"},
    {"name": "Ditto", "url": "https://media.tenor.com/IA266nP_INIAAAAM/ditto-pokemon.gif"}
]

# ---------------------------
# Cog
# ---------------------------
class RocketDial(commands.Cog):
    """🚀 Rocket Dial — in-memory multi-server dial with aliases, idle monitor, and reporting."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # active calls: key = guild_id (str), value = dict with call info
        self.calls: Dict[str, Dict[str, Any]] = {}
        # waiting_calls: key = guild_id (str), value = (channel, webhook, task)
        self.waiting_calls: Dict[str, Tuple[discord.TextChannel, discord.Webhook, asyncio.Task]] = {}
        # map of pairs for convenience
        self.active_pairs: Dict[str, str] = {}
        # remember which member started a waiting call (so both sides are initiators)
        self.waiting_initiator: Dict[str, int] = {}
        # used to avoid spamming warning messages per user per call
        # report tracking
        self.user_reports: Dict[int, int] = {}
        self.report_reset_day: Optional[datetime.date] = None

        self.answer_timeout = 30
        self.idle_timeout = 30 * 60  # 30 minutes default idle
        print("[RocketDial] initialized (memory-only)")

    # ---------------------------
    # Utilities
    # ---------------------------
    BAD_WORDS = ["fuck", "shit", "bitch", "asshole","btch","fck","sht"]  # extend as needed

    def censor_message(self, text: str) -> str:
        words = text.split()
        censored_words = []
        for word in words:
            lower = word.lower()
            clean_word = word
            for bad in self.BAD_WORDS:
                if bad in lower:
                    clean_word = "*" * (len(bad) - 1) + word[-1]
                    break
            censored_words.append(clean_word)
        return " ".join(censored_words)

    def find_dial_channel(self, guild: discord.Guild) -> Optional[discord.TextChannel]:
        for ch in guild.text_channels:
            if "rocket-dial" in ch.name.lower():
                return ch
        return None

    def pick_two_unique_aliases(self):
        a, b = random.sample(POKEMON_GIFS, 2)
        # return entries matching structure used elsewhere: {"name": ..., "url": ...}
        return {"name": a["name"], "url": a["url"]}, {"name": b["name"], "url": b["url"]}

    async def get_or_create_webhook(self, channel: discord.TextChannel, name: str):
        try:
            existing_webhooks = await channel.webhooks()
            for wh in existing_webhooks:
                # prefer a webhook created by the bot if available
                if wh.user == self.bot.user and wh.name == name:
                    return wh
            # else create new
            wh = await channel.create_webhook(name=name)
            return wh
        except discord.Forbidden:
            print(f"[DEBUG] No permission to create webhook in {channel.name}")
            return None
        except Exception as e:
            print(f"[RocketDial] get_or_create_webhook error: {e}")
            return None

    async def safe_delete_webhook(self, wh: Optional[discord.Webhook]):
        try:
            if wh:
                await wh.delete()
        except Exception as e:
            print(f"[RocketDial] safe_delete_webhook failed: {e}")

    async def _hangup_pair(
            self,
            gid_a: str,
            reason_initiator: Optional[str] = None,
            notify_both: bool = True,
            initiator_guild_id: Optional[int] = None
    ):
        """
        End the call between gid_a and its partner.
        Keeps original behavior but ensures only the *other* side gets notified
        when one guild manually hangs up.
        """
        info_a = self.calls.pop(gid_a, None)
        partner = info_a.get("partner") if info_a else self.active_pairs.pop(gid_a, None)
        if partner:
            self.active_pairs.pop(str(partner), None)
        info_b = self.calls.pop(str(partner), None) if partner else None

        # Cancel idle monitor & delete webhooks
        for info in [info_a, info_b]:
            if info and info.get("idle_task"):
                try:
                    info["idle_task"].cancel()
                except Exception:
                    pass
            if info and info.get("webhook"):
                try:
                    await self.safe_delete_webhook(info["webhook"])
                except Exception:
                    pass

        # ✅ Notify both sides — but skip message on the guild that initiated hangup
        try:
            for gid in [gid_a, str(partner)]:
                if not gid:
                    continue
                g = self.bot.get_guild(int(gid))
                if not g:
                    continue
                ch = self.find_dial_channel(g)
                if not ch:
                    continue

                # ✅ Only send message to the *other* side
                if initiator_guild_id and int(gid) == initiator_guild_id:
                    continue  # skip notifying the initiator

                await ch.send("📴 **The other side hung up. The call has ended.**")

        except Exception as e:
            print(f"[RocketDial] notify error during hangup: {e}")

    # ---------------------------
    # Helper to read admin reported channel and get report count
    # ---------------------------
    async def get_report_count(self, user_id: int) -> int:
        """
        Reads the ADMIN_REPORTED_MEMBERS channel and returns the report count for user_id.
        Format expected: "{user_id} | {alias} | {Nx} | Reason: ...".
        Returns 0 if not found, capped at 3.
        """
        try:
            reported_channel_id = int(os.environ.get("ADMIN_REPORTED_MEMBERS", 0))
        except Exception:
            return 0
        if not reported_channel_id:
            return 0
        main_guild_id = int(os.environ.get("MY_MAIN_GUILD", 0)) if os.environ.get("MY_MAIN_GUILD") else 0
        if not main_guild_id:
            return 0
        main_guild = self.bot.get_guild(main_guild_id)
        if not main_guild:
            return 0
        channel = main_guild.get_channel(reported_channel_id)
        if not channel:
            return 0

        try:
            async for msg in channel.history(limit=500):
                # guard against empty or unexpected formats
                parts = msg.content.split("|")
                if not parts:
                    continue
                if parts[0].strip() == str(user_id):
                    # parts[2] expected like "1x" or "2x" or "3x"
                    if len(parts) > 2:
                        try:
                            count_token = parts[2].strip()
                            count = int(''.join(ch for ch in count_token if ch.isdigit()))
                            return min(count, 3)
                        except Exception:
                            return 0
            return 0
        except Exception:
            return 0

    # ---------------------------
    # rd group (command guide) — keep original message exactly
    # ---------------------------
    @commands.group(name="rd", invoke_without_command=True, help="Rocket Dial command guide")
    async def rd(self, ctx: commands.Context):
        msg = (
            "📖 Rocket Dial Commands\n"
            "`.rd call` or `.rdc` — Start a Rocket Dial call to another server\n"
            "`.rd hangup` or `.rdh` — End the current Rocket Dial call\n"
            "`.rd unveil` or `.rdu` — Reveal your identity to the other server\n"
            "`.rd report` or `.rdr` — Report a member for misconduct\n"
            "`.rd friend` or `.rdfr` — Send a friend request\n"
            "`.rd` — Show this command guide\n"
            "💡 Tip: The dial ends automatically after 30 seconds if no one answers."
        )
        await ctx.send(msg)

    # ---------------------------
    # Shortcut commands
    # ---------------------------
    @commands.command(name="rdc")
    async def rdc(self, ctx: commands.Context):
        await ctx.invoke(self.bot.get_command("rd call"))

    @commands.command(name="rdh")
    async def rdh(self, ctx: commands.Context):
        await ctx.invoke(self.bot.get_command("rd hangup"))

    @commands.command(name="rdu")
    async def rdu_alias(self, ctx: commands.Context):
        await ctx.invoke(self.rd_unveil)

    @commands.command(name="rdr")
    async def rdr_alias(self, ctx: commands.Context, *, reason: str = None):
        await ctx.invoke(self.rd_report, reason=reason)

    @commands.command(name="rdfr")
    async def rdfr_alias(self, ctx: commands.Context):
        await ctx.invoke(self.rd_friend)

    # ---------------------------
    # rd call
    # ---------------------------
    @rd.command(name="call")
    async def rd_call(self, ctx: commands.Context):
        if not isinstance(ctx.channel, discord.TextChannel) or "rocket-dial" not in ctx.channel.name.lower():
            return await ctx.send("⚠️ Please run this command inside a channel with `rocket-dial` in its name.")

        guild_id = str(ctx.guild.id)
        caller_member_id = ctx.author.id  # store as int

        # Check current call/waiting status
        if guild_id in self.calls:
            return await ctx.send("📞 Your server is already in a Rocket Dial call. Use `.rd hangup` first.")
        if guild_id in self.waiting_calls:
            return await ctx.send("📞 You already placed a call, please wait for another server to answer.")

        # Check caller report status
        caller_report_count = await self.get_report_count(caller_member_id)
        if caller_report_count >= 3:
            return await ctx.send(
                f"🚫 You are banned from Rocket Dial due to 3 reports.\n" 
                "🚫 You cannot start calls or send messages.\n"
                "Visit RocketBot official page to appeal or lift the ban."
            )
        elif caller_report_count in (1, 2):
            await ctx.send(
                f"⚠️ You have {caller_report_count} report(s) on record. Please behave properly; you can still start the call.")

        # Create/get webhook
        webhook = await self.get_or_create_webhook(ctx.channel, f"Rocket Dial - Friend Request")
        if webhook is None:
            return await ctx.send("⚠️ I need 'Manage Webhooks' permission to start Rocket Dial.")

        # Send Dialing message immediately
        msg = await ctx.send(
            "📞 **Dialing...**\n🚀 Waiting for another server to pick up. Call will auto-hangup in 30 seconds if unanswered."
        )

        # Look for waiting partner
        partner_entry = None
        for other_gid, (o_channel, o_webhook, o_task) in list(self.waiting_calls.items()):
            if other_gid == guild_id:
                continue
            waiting_initiator_id = self.waiting_initiator.get(other_gid)
            # Skip banned partners
            if waiting_initiator_id and await self.get_report_count(waiting_initiator_id) >= 3:
                try:
                    _, wh, t = self.waiting_calls.pop(other_gid)
                    t.cancel()
                    await self.safe_delete_webhook(wh)
                except Exception:
                    pass
                self.waiting_initiator.pop(other_gid, None)
                continue
            partner_entry = (other_gid, o_channel, o_webhook, o_task)
            break

        if partner_entry:
            # Partner found → connect immediately
            other_gid, other_channel, other_webhook, other_task = partner_entry
            try:
                other_task.cancel()
            except Exception:
                pass
            del self.waiting_calls[other_gid]

            # Pick aliases
            alias_a, alias_b = self.pick_two_unique_aliases()
            now = asyncio.get_event_loop().time()
            waiting_initiator_id = self.waiting_initiator.get(other_gid)

            # Create initiators set
            initiators = {caller_member_id}
            if waiting_initiator_id:
                initiators.add(waiting_initiator_id)

            # Assign calls and active pairs
            self.calls[guild_id] = {
                "partner": other_gid,
                "webhook": webhook,
                "user_aliases": {caller_member_id: alias_a},
                "revealed_users": set(),
                "idle_task": None,
                "last_activity": now,
                "caller_member_id": caller_member_id,
                "initiators": initiators,
                "warned_users": set(),
            }
            self.calls[other_gid] = {
                "partner": guild_id,
                "webhook": other_webhook,
                "user_aliases": {},  # will be assigned when users type
                "revealed_users": set(),
                "idle_task": None,
                "last_activity": now,
                "caller_member_id": waiting_initiator_id,
                "initiators": initiators,
                "warned_users": set(),
            }

            self.active_pairs[guild_id] = other_gid
            self.active_pairs[other_gid] = guild_id

            # Notify both sides
            try:
                await msg.edit(content="📡 **Call connected!** Users will now be masked as Pokémon aliases.")
            except Exception:
                pass
            try:
                await other_channel.send("📡 **Call connected!** Users will now be masked as Pokémon aliases.")
            except Exception:
                pass

            # Warn if partner had 1-2 reports
            if waiting_initiator_id:
                waiting_count = await self.get_report_count(waiting_initiator_id)
                if waiting_count in (1, 2):
                    try:
                        g = self.bot.get_guild(int(other_gid))
                        if g:
                            ch = self.find_dial_channel(g)
                            if ch:
                                await ch.send(
                                    f"⚠️ Note: The user who initiated this call has {waiting_count} report(s) on record.")
                    except Exception:
                        pass

            # Start idle monitor
            idle_task = asyncio.create_task(self._idle_monitor_pair(guild_id, other_gid))
            self.calls[guild_id]["idle_task"] = idle_task
            self.calls[other_gid]["idle_task"] = idle_task

            if other_gid in self.waiting_initiator:
                del self.waiting_initiator[other_gid]
            return

        # No partner → start countdown
        async def precall_countdown_and_cleanup():
            try:
                for remaining in range(self.answer_timeout, 0, -5):
                    await asyncio.sleep(5)
                    if guild_id not in self.waiting_calls:
                        return
                    try:
                        await msg.edit(
                            content=f"📞 **Dialing...**\n🚀 Waiting for another server to pick up. Auto-hangup in {remaining} seconds."
                        )
                    except Exception:
                        pass
                if guild_id in self.waiting_calls:
                    _, waiting_webhook, _ = self.waiting_calls.pop(guild_id)
                    try:
                        await self.safe_delete_webhook(waiting_webhook)
                    except Exception:
                        pass
                    try:
                        await msg.edit(
                            content="📴 **No one picked up.** The Rocket Dial hung up automatically after 30 seconds."
                        )
                    except Exception:
                        try:
                            await ctx.send(
                                "📴 **No one picked up.** The Rocket Dial hung up automatically after 30 seconds."
                            )
                        except Exception:
                            pass
            except asyncio.CancelledError:
                return
            except Exception as e:
                print(f"[RocketDial] precall_countdown_and_cleanup error: {e}")

        auto_task = asyncio.create_task(precall_countdown_and_cleanup())
        self.waiting_calls[guild_id] = (ctx.channel, webhook, auto_task)
        self.waiting_initiator[guild_id] = caller_member_id

    # ---------------------------
    # rd hangup
    # ---------------------------
    @rd.command(name="hangup")
    async def rd_hangup(self, ctx: commands.Context):
        guild_id = str(ctx.guild.id)

        # --- If the call is still in "waiting" (not yet connected)
        if guild_id in self.waiting_calls:
            _, wh, task = self.waiting_calls.pop(guild_id)
            try:
                task.cancel()
            except Exception:
                pass
            await self.safe_delete_webhook(wh)
            return await ctx.send("📴 Call canceled before connection.")

        # --- If there’s no active call
        if guild_id not in self.calls:
            return await ctx.send("📴 You are not in an active Rocket Dial call.")

        # --- Otherwise, hang up an active call
        partner_id = self.calls[guild_id]["partner"]

        # ✅ pass initiator guild id so we don’t broadcast back to self
        await self._hangup_pair(
            guild_id,
            reason_initiator=ctx.author.display_name,
            initiator_guild_id=ctx.guild.id
        )

        return await ctx.send("📞 You hung up the Rocket Dial call. Call ended.")
    # ---------------------------
    # rd unveil
    # ---------------------------
    @rd.command(name="unveil")
    async def rd_unveil(self, ctx: commands.Context):
        guild_id = str(ctx.guild.id)
        if guild_id not in self.calls:
            return await ctx.send("⚠️ You are not in an active Rocket Dial call.")

        call_info = self.calls[guild_id]
        revealed = call_info.setdefault("revealed_users", set())

        if ctx.author.id in revealed:
            return await ctx.send("⚠️ You already unveiled yourself.")

        revealed.add(ctx.author.id)

        partner_guild_id = str(call_info.get("partner"))
        if not partner_guild_id or partner_guild_id not in self.calls:
            return await ctx.send("⚠️ Your partner is no longer connected.")

        partner_guild = self.bot.get_guild(int(partner_guild_id))
        partner_chan = self.find_dial_channel(partner_guild)
        if not partner_chan:
            return await ctx.send("⚠️ Could not find partner's dial channel.")

        real_name = ctx.author.display_name
        real_avatar = ctx.author.display_avatar.url

        embed = discord.Embed(
            title="💫 Rocket Dial: Unveil!",
            description=f"**{real_name}** has bravely unveiled their true identity!",
            color=discord.Color.purple()
        )
        embed.set_thumbnail(url=real_avatar)
        embed.set_footer(text="🚀 Identity Transmission Complete")

        await partner_chan.send(embed=embed)
        await ctx.send("✅ You have unveiled your true identity to the other caller.")

        # Mark unveiled for message display
        call_info["revealed_users"].add(ctx.author.id)

    # ---------------------------
    # .rd report / .rdr
    # ---------------------------
    @rd.command(name="report", aliases=["rdr"])
    async def rd_report(self, ctx: commands.Context, *, reason: str = "No reason provided"):
        import datetime, os
    
        today = datetime.date.today()
        if self.report_reset_day != today:
            self.user_reports.clear()
            self.report_reset_day = today
    
        guild_id = str(ctx.guild.id)
        call_info = self.calls.get(guild_id)
        if not call_info:
            return await ctx.send("⚠️ You are not in an active Rocket Dial call.")
    
        # Partner info
        partner_guild_id = call_info.get("partner")
        partner_call_info = self.calls.get(str(partner_guild_id))
        if not partner_call_info:
            return await ctx.send("⚠️ Cannot find the member on the other server.")
    
        reporter = ctx.author
        reporter_id = reporter.id
    
        # Track warned messages to avoid duplicates
        warned_set = self.user_reports.setdefault(reporter_id, set())
    
        # -------------------------------
        # Check initiators (only original initiators can file reports)
        # -------------------------------
        initiators = {i for i in call_info.get("initiators", set()) if isinstance(i, int)}
        if reporter_id not in initiators:
            first_initiator = next(iter(initiators), None)
            mention = f"<@{first_initiator}>" if first_initiator else "the initiator"
            return await ctx.send(
                f"⚠️ You are not one of the original initiators. Only the two who started this call can report. ({mention})"
            )
    
        # Determine reported member id and alias
        partner_member_id = partner_call_info.get("caller_member_id")
        if not partner_member_id:
            return await ctx.send(
                "⚠️ Cannot report this member because their identity could not be verified."
            )
    
        user_aliases = partner_call_info.get("user_aliases", {})
        reported_alias = next(iter(user_aliases.values()))["name"] if user_aliases else "Unknown Pokémon"
    
        # Sanitize reason
        reason = (reason or "No reason provided").strip()
        reason = reason.replace("|", "/")  # avoid breaking the format
    
        # -------------------------------
        # Admin channels
        # -------------------------------
        try:
            main_guild_id = int(os.environ.get("MY_MAIN_GUILD", 0))
            reported_channel_id = int(os.environ.get("ADMIN_REPORTED_MEMBERS", 0))
            reporter_channel_id = int(os.environ.get("ADMIN_REPORTER_MEMBERS", 0))
        except Exception:
            return await ctx.send("⚠️ Admin channels not configured properly.")
    
        main_guild = self.bot.get_guild(main_guild_id)
        if not main_guild:
            return await ctx.send("⚠️ Main guild not found.")
    
        reported_channel = main_guild.get_channel(reported_channel_id) if main_guild else None
        reporter_channel = main_guild.get_channel(reporter_channel_id) if main_guild else None
    
        # -------------------------------
        # Check reporter max reports
        # -------------------------------
        reporter_count = 0
        if reporter_channel:
            try:
                async for msg in reporter_channel.history(limit=200):
                    parts = msg.content.split("|", maxsplit=3)
                    if parts[0].strip() == str(reporter_id):
                        reporter_count = int(parts[2].strip().replace("x", ""))
                        break
            except Exception:
                pass
    
        # Prevent duplicate max-report message
        if reporter_count >= 3:
            if "max_report_warned" not in warned_set:
                await ctx.send("⚠️ You have reached the maximum number of reports (3).")
                warned_set.add("max_report_warned")
            return
    
        # -------------------------------
        # Update reported member record
        # -------------------------------
        reported_count = 1
        if reported_channel:
            try:
                last_msg = None
                async for msg in reported_channel.history(limit=200):
                    parts = msg.content.split("|", maxsplit=3)
                    if parts[0].strip() == str(partner_member_id):
                        last_msg = msg
                        break
                if last_msg:
                    parts = last_msg.content.split("|", maxsplit=3)
                    current_count = int(parts[2].strip().replace("x", ""))
                    reported_count = min(current_count + 1, 3)
                    new_content = f"{partner_member_id} | {reported_alias} | {reported_count}x | {reason}"
                    # Only edit if content changed
                    if last_msg.content != new_content:
                        await last_msg.edit(content=new_content)
                else:
                    await reported_channel.send(
                        f"{partner_member_id} | {reported_alias} | {reported_count}x | {reason}")
            except Exception as e:
                print(f"[rd_report] Failed updating reported channel: {e}")
    
        # -------------------------------
        # Update reporter record
        # -------------------------------
        reporter_count += 1
        if reporter_channel:
            try:
                last_msg = None
                async for msg in reporter_channel.history(limit=200):
                    parts = msg.content.split("|", maxsplit=3)
                    if parts[0].strip() == str(reporter_id):
                        last_msg = msg
                        break
                if last_msg:
                    new_reporter_content = f"{reporter_id} | {reporter.display_name} | {reporter_count}x"
                    if last_msg.content != new_reporter_content:
                        await last_msg.edit(content=new_reporter_content)
                else:
                    await reporter_channel.send(f"{reporter_id} | {reporter.display_name} | {reporter_count}x")
            except Exception as e:
                print(f"[rd_report] Failed updating reporter channel: {e}")
    
        # -------------------------------
        # Confirm & hangup
        # -------------------------------
        await ctx.send(f"✅ You reported **{reported_alias}** for: {reason} ({reported_count}/3 reports)")
        await self._hangup_pair(guild_id, notify_both=True)

    # ---------------------------
    # .rd friend / .rdfr
    # ---------------------------
    @rd.command(name="friend", aliases=["rdfr"])
    async def rd_friend(self, ctx: commands.Context):
        guild_id = str(ctx.guild.id)
        call_info = self.calls.get(guild_id)

        if not call_info:
            return await ctx.send("⚠️ You are not in an active Rocket Dial call.")

        partner_guild_id = call_info.get("partner")
        partner_call_info = self.calls.get(str(partner_guild_id))

        if not partner_call_info:
            return await ctx.send("⚠️ Cannot find the member on the other server.")

        sender_user = ctx.author
        sender_discord_tag = str(sender_user)  # Username#1234

        partner_webhook = partner_call_info.get("webhook")
        if not partner_webhook:
            return await ctx.send("⚠️ Cannot send friend request. Partner webhook not found.")

        try:
            await partner_webhook.send(
                content=f"💌 You have received a friend request from other caller: **{sender_discord_tag}**"
            )
            await ctx.send("✅ Your friend request has been sent to the other caller.")
        except Exception as e:
            await ctx.send(f"⚠️ Failed to send friend request: {e}")

    # ---------------------------
    # Idle monitoring for pairs
    # ---------------------------
    async def _idle_monitor_pair(self, gid_a: str, gid_b: str):
        while True:
            await asyncio.sleep(self.idle_timeout)
            now = asyncio.get_event_loop().time()
            for gid in [gid_a, gid_b]:
                call_info = self.calls.get(gid)
                if not call_info:
                    continue
                last = call_info.get("last_activity", now)
                if now - last > self.idle_timeout:
                    await self._hangup_pair(gid)
                    return

    # on_message forwarding (full, preserves original behavior + sets initiator + report checks)
    # ---------------------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Ignore bots/webhooks/system messages
        if message.author.bot or not message.guild or message.webhook_id:
            return
        if not isinstance(message.channel, discord.TextChannel):
            return
        if "rocket-dial" not in message.channel.name.lower():
            return

        guild_id = str(message.guild.id)
        if guild_id not in self.calls:
            return

        call_info = self.calls[guild_id]
        partner_id = call_info.get("partner")
        if not partner_id:
            return

        partner_info = self.calls.get(str(partner_id))
        if not partner_info:
            return

        member = message.author
        call_info["last_activity"] = asyncio.get_event_loop().time()
        target_webhook = partner_info.get("webhook")
        if not target_webhook:
            print(f"[RocketDial] Partner webhook missing for guild {partner_id}")
            return

        # ---------------------------
        # 1️⃣ Check banned users (3+ reports)
        # ---------------------------
        report_count = await self.get_report_count(member.id)
        # In on_message
        if report_count >= 3:
            try:
                await message.delete()
            except:
                pass
            try:
                await message.channel.send(
                    f"🚫 {member.mention}, you are banned from Rocket Dial due to 3 reports.\n"
                    "You cannot send messages or start calls.\n"
                    "Visit RocketBot official page to appeal or lift the ban.",
                    delete_after=10
                )
            except:
                pass

            # ✅ Do NOT hang up the call for joiners
            return

        # ---------------------------
        # 2️⃣ Warn for 1-2 reports
        # ---------------------------
        warned_set = call_info.setdefault("warned_users", set())
        if report_count in (1, 2) and member.id not in warned_set:
            try:
                await message.channel.send(
                    f"⚠️ {member.mention}, you have {report_count} report(s) on record. Please behave properly."
                )
            except Exception:
                pass
            warned_set.add(member.id)

        # ---------------------------
        # 3️⃣ Initiator tracking
        # ---------------------------
        if not call_info.get("caller_member_id"):
            call_info["caller_member_id"] = member.id
            initiators = call_info.setdefault("initiators", set())
            initiators.add(member.id)
            partner_inits = partner_info.setdefault("initiators", set())
            partner_inits.update(initiators)

        # ---------------------------
        # 4️⃣ Alias / Pokémon display
        # ---------------------------
        alias_map = call_info.setdefault("user_aliases", {})
        if member.id not in alias_map:
            used_aliases = {v["name"] for v in alias_map.values()}
            available_aliases = [p for p in POKEMON_GIFS if p["name"] not in used_aliases]
            if not available_aliases:
                available_aliases = POKEMON_GIFS
            alias_entry = random.choice(available_aliases)
            alias_map[member.id] = alias_entry
        else:
            alias_entry = alias_map[member.id]

        revealed_users = call_info.get("revealed_users", set())
        if member.id in revealed_users:
            display_name = member.display_name
            avatar_url = member.display_avatar.url
        else:
            display_name = alias_entry.get("name", "Pokémon")
            avatar_url = alias_entry.get("url", member.display_avatar.url)

        # ---------------------------
        # 5️⃣ File/link restrictions
        # ---------------------------
        if message.attachments:
            try:
                await message.delete()
            except Exception:
                pass
            try:
                await message.channel.send(f"🚫 {member.mention}, file attachments are not allowed.", delete_after=8)
            except Exception:
                pass
            return

        if "http://" in message.content or "https://" in message.content:
            lower_msg = message.content.lower()
            # Allow Tenor links only for Gold Members
            if "tenor.com" in lower_msg:
                gold_channel_id = int(os.getenv("ADMIN_GOLD_MEMBERS", 0))
                gold_member_ids = set()
                if gold_channel_id:
                    gold_channel = self.bot.get_channel(gold_channel_id)
                    if gold_channel:
                        try:
                            async for msg in gold_channel.history(limit=100):
                                uid = int(msg.content.split("|")[0].strip())
                                gold_member_ids.add(uid)
                        except Exception:
                            pass
                if member.id not in gold_member_ids:
                    try:
                        await message.delete()
                    except Exception:
                        pass
                    try:
                        await message.channel.send(
                            f"🚫 Sorry {member.mention}, only Premium members can send Tenor GIFs.\n"
                            "Visit RocketBot's official page to get Premium.",
                            delete_after=8

                        )
                    except Exception:
                        pass
                    return
            else:
                try:
                    await message.delete()
                except Exception:
                    pass
                try:
                    await message.channel.send(f"🚫 {member.mention}, external links are not allowed.", delete_after=8)
                except Exception:
                    pass
                return

        # ---------------------------
        # 6️⃣ Censor bad words
        # ---------------------------
        censored_content = self.censor_message(message.content)

        # ---------------------------
        # 7️⃣ Forward to partner
        # ---------------------------
        try:
            await target_webhook.send(
                content=censored_content,
                username=display_name,
                avatar_url=avatar_url
            )
        except Exception as e:
            print(f"[RocketDial] forward message error: {e}")

        # ---------------------------
        # 8️⃣ Ensure commands still work
        # ---------------------------
        await self.bot.process_commands(message)


# ---------------------------
# Setup
# ---------------------------
async def setup(bot: commands.Bot):
    await bot.add_cog(RocketDial(bot))
