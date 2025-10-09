# rocket_dial.py
import discord
from discord.ext import commands
import asyncio
import random
from typing import Dict, Optional, Tuple, Any
import datetime
import os

# ---------------------------
# Pokémon GIFs
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
        self.calls: Dict[str, Dict[str, Any]] = {}
        self.waiting_calls: Dict[str, Tuple[discord.TextChannel, discord.Webhook, asyncio.Task]] = {}
        self.active_pairs: Dict[str, str] = {}
        self.answer_timeout = 30
        self.idle_timeout = 30
        self.user_reports: Dict[int, int] = {}
        self.report_reset_day: Optional[datetime.date] = None
        print("[RocketDial] initialized (memory-only)")

    # ---------------------------
    # Utilities
    # ---------------------------
    def find_dial_channel(self, guild: discord.Guild) -> Optional[discord.TextChannel]:
        for ch in guild.text_channels:
            if "rocket-dial" in ch.name.lower():
                return ch
        return None

    def pick_two_unique_aliases(self):
        a, b = random.sample(POKEMON_GIFS, 2)
        return {"name": a["name"], "gif": a["url"]}, {"name": b["name"], "gif": b["url"]}

    async def get_or_create_webhook(self, channel: discord.TextChannel, name: str):
        try:
            existing_webhooks = await channel.webhooks()
            for wh in existing_webhooks:
                if wh.name == name:
                    return wh
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

    async def _hangup_pair(self, gid_a: str, reason_initiator: Optional[str] = None, notify_both: bool = True):
        info_a = self.calls.pop(gid_a, None)
        partner = info_a.get("partner") if info_a else self.active_pairs.pop(gid_a, None)
        if partner:
            self.active_pairs.pop(str(partner), None)
        info_b = self.calls.pop(str(partner), None) if partner else None

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
            if info and "rdr_initiator" in info:
                del info["rdr_initiator"]

        try:
            for gid in [gid_a, str(partner)]:
                g = self.bot.get_guild(int(gid)) if gid else None
                if g and notify_both:
                    ch = self.find_dial_channel(g)
                    if ch:
                        await ch.send("📴 **The call has ended.**")
        except Exception as e:
            print(f"[RocketDial] notify error during hangup: {e}")

    # ---------------------------
    # rd group
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
    async def rdr_alias(self, ctx: commands.Context):
        await ctx.invoke(self.rd_report)

    @commands.command(name="rdfr")
    async def rdfr_alias(self, ctx: commands.Context):
        await ctx.invoke(self.rd_friend)

    # ---------------------------
    # rd call
    # ---------------------------
    @rd.command(name="call")
    async def rd_call(self, ctx: commands.Context, idle_task=None):
        if not isinstance(ctx.channel, discord.TextChannel) or "rocket-dial" not in ctx.channel.name.lower():
            return await ctx.send("⚠️ Please run this command inside a channel with `rocket-dial` in its name.")

        guild_id = str(ctx.guild.id)
        caller_member_id = str(ctx.author.id)  # the member starting the call

        # -------------------------------
        # CHECK IF MEMBER IS REPORTED 3X (ADMIN_REPORTED_MEMBERS)
        # -------------------------------
        main_guild_id = int(os.environ.get("MAIN_GUILD", 0))
        reported_channel_id = int(os.environ.get("ADMIN_REPORTED_MEMBERS", 0))

        main_guild = self.bot.get_guild(main_guild_id)
        reported_channel = main_guild.get_channel(reported_channel_id) if main_guild else None

        reported_count = 0
        if reported_channel:
            try:
                # Check last 100 messages in reported channel, newest first
                async for msg in reported_channel.history(limit=100, oldest_first=False):
                    parts = msg.content.split("|")
                    if len(parts) >= 3:
                        member_id = parts[0].strip()  # treat as string
                        count_part = parts[2].strip()  # "1x", "2x", etc.
                        count = int(count_part.replace("x", ""))
                        if member_id == caller_member_id:
                            reported_count = count
                            break
            except Exception as e:
                print(f"[rd_call] Error reading reported channel: {e}")

        if reported_count >= 3:
            return await ctx.send(
                f"⛔ You have been reported {reported_count} times by other callers and are banned from Rocket Dial for 1 week. Visit the official website and contact an admin to lift your ban."
            )

        # -------------------------------
        # EXISTING CALL LOGIC
        # -------------------------------
        if guild_id in self.calls:
            return await ctx.send("📞 Your server is already in a Rocket Dial call. Use `.rd hangup` to end it first.")
        if guild_id in self.waiting_calls:
            return await ctx.send("📞 You already placed a call, please wait for another server to answer.")

        webhook = await self.get_or_create_webhook(ctx.channel, f"Rocket Dial - Friend Request")
        if webhook is None:
            return await ctx.send("⚠️ I need 'Manage Webhooks' permission to start Rocket Dial.")

        # find waiting partner
        partner_entry = None
        for other_gid, (o_channel, o_webhook, o_task) in self.waiting_calls.items():
            if other_gid != guild_id:
                partner_entry = (other_gid, o_channel, o_webhook, o_task)
                break

        if partner_entry:
            other_gid, other_channel, other_webhook, other_task = partner_entry
            try:
                other_task.cancel()
            except Exception:
                pass
            del self.waiting_calls[other_gid]

            alias_a, alias_b = self.pick_two_unique_aliases()
            now = asyncio.get_event_loop().time()
            self.calls[guild_id] = {
                "partner": other_gid,
                "webhook": webhook,
                "user_aliases": {},
                "revealed_users": set(),
                "idle_task": idle_task,
                "last_activity": now,
                "caller_member_id": caller_member_id
            }
            self.calls[other_gid] = {
                "partner": guild_id,
                "webhook": other_webhook,
                "user_aliases": {},
                "revealed_users": set(),
                "idle_task": idle_task,
                "last_activity": now,
                "caller_member_id": None
            }

            self.active_pairs[guild_id] = other_gid
            self.active_pairs[other_gid] = guild_id

            await ctx.send("📡 **Call connected!** Users will now be masked as Pokémon aliases (silent mode).")
            await other_channel.send("📡 **Call connected!** Users will now be masked as Pokémon aliases (silent mode).")

            try:
                other_guild = self.bot.get_guild(int(other_gid))
                if other_guild:
                    await ctx.author.send(f"ℹ️ The other caller's server name is **{other_guild.name}**")
            except Exception:
                if other_guild:
                    sent_msg = await ctx.send(
                        f"ℹ️ Could not DM you, but the other caller's server name is **{other_guild.name}**"
                    )
                    await asyncio.sleep(10)
                    try:
                        await sent_msg.delete()
                    except Exception:
                        pass

            idle_task = asyncio.create_task(self._idle_monitor_pair(guild_id, other_gid))
            self.calls[guild_id]["idle_task"] = idle_task
            self.calls[other_gid]["idle_task"] = idle_task
            return

        msg = await ctx.send(
            "📞 **Dialing...**\n🚀 Waiting for another server to pick up. Call will auto-hangup in 30 seconds if unanswered."
        )

        async def precall_countdown_and_cleanup():
            try:
                for remaining in range(self.answer_timeout, 0, -5):
                    await asyncio.sleep(5)
                    if guild_id not in self.waiting_calls: return
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
                            content="📴 **No one picked up.** The Rocket Dial hung up automatically after 30 seconds ")
                    except Exception:
                        try:
                            await ctx.send(
                                "📴 **No one picked up.** The Rocket Dial hung up automatically after 30 seconds")
                        except Exception:
                            pass
            except asyncio.CancelledError:
                return
            except Exception as e:
                print(f"[RocketDial] precall_countdown_and_cleanup error: {e}")

        auto_task = asyncio.create_task(precall_countdown_and_cleanup())
        self.waiting_calls[guild_id] = (ctx.channel, webhook, auto_task)

    # ---------------------------
    # rd hangup
    # ---------------------------
    @rd.command(name="hangup")
    async def rd_hangup(self, ctx: commands.Context):
        guild_id = str(ctx.guild.id)
        if guild_id in self.waiting_calls:
            _, wh, task = self.waiting_calls.pop(guild_id)
            try: task.cancel()
            except Exception: pass
            await self.safe_delete_webhook(wh)
            return await ctx.send("📴 Call canceled before connection.")
        if guild_id not in self.calls:
            return await ctx.send("📴 You are not in an active Rocket Dial call.")
        partner_id = self.calls[guild_id]["partner"]
        await self._hangup_pair(guild_id, reason_initiator=ctx.author.display_name)
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
        partner_id = call_info["partner"]
        partner_guild = self.bot.get_guild(int(partner_id))
        if partner_guild:
            partner_chan = self.find_dial_channel(partner_guild)
            if partner_chan:
                await partner_chan.send(f"🚀 Unveil! **{ctx.author.display_name}** has revealed themselves!")
        await ctx.send("✅ Your identity has been unveiled to the other server.")


    # ---------------------------
    # .rd report / .rdr
    # ---------------------------
    @rd.command(name="report", aliases=["rdr"])
    async def rd_report(self, ctx: commands.Context, *, reason: str = "No reason provided"):
        # -------------------------------
        # Daily reset
        # -------------------------------
        today = datetime.date.today()
        if self.report_reset_day != today:
            self.user_reports.clear()
            self.report_reset_day = today

        guild_id = str(ctx.guild.id)
        call_info = self.calls.get(guild_id)
        if not call_info:
            return await ctx.send("⚠️ You are not in an active Rocket Dial call.")

        # -------------------------------
        # Get partner guild and member
        # -------------------------------
        partner_guild_id = call_info.get("partner")
        partner_call_info = self.calls.get(str(partner_guild_id))
        if not partner_call_info:
            return await ctx.send("⚠️ Cannot find the member on the other server.")

        partner_member_id = partner_call_info.get("caller_member_id")
        if not partner_member_id:
            return await ctx.send(
                "⚠️ Cannot report this member because their identity could not be verified. Only valid callers can be reported."
            )

        # -------------------------------
        # Get alias
        # -------------------------------
        user_aliases = partner_call_info.get("user_aliases", {})
        reported_alias = next(iter(user_aliases.values()))["name"] if user_aliases else "Unknown Pokémon"

        reporter = ctx.author

        # -------------------------------
        # Sanitize reason
        # -------------------------------
        reason = reason.strip()
        if not reason:
            reason = "No reason provided"
        reason = reason.replace("|", "/")  # prevent breaking message format

        # -------------------------------
        # Environment channels
        # -------------------------------
        main_guild_id = int(os.environ.get("MAIN_GUILD", 0))
        reported_channel_id = int(os.environ.get("ADMIN_REPORTED_MEMBERS", 0))
        reporter_channel_id = int(os.environ.get("ADMIN_REPORTER_MEMBERS", 0))

        main_guild = self.bot.get_guild(main_guild_id)
        reported_channel = main_guild.get_channel(reported_channel_id) if main_guild else None
        reporter_channel = main_guild.get_channel(reporter_channel_id) if main_guild else None

        # -------------------------------
        # Check reporter max reports (3x)
        # -------------------------------
        reporter_count = 0
        if reporter_channel:
            try:
                async for msg in reporter_channel.history(limit=100):
                    if msg.content.split("|")[0].strip() == str(reporter.id):
                        parts = msg.content.split("|")
                        reporter_count = int(parts[2].strip().replace("x", ""))
                        break
            except Exception:
                pass

        if reporter_count >= 3:
            return await ctx.send(
                f"⚠️ You have reached the maximum number of reports (3). You cannot report any more members today."
            )

        # -------------------------------
        # Update reported member
        # -------------------------------
        reported_count = 1
        if reported_channel:
            try:
                last_msg = None
                async for msg in reported_channel.history(limit=100):
                    if msg.content.split("|")[0].strip() == str(partner_member_id):
                        last_msg = msg
                        break
                if last_msg:
                    parts = last_msg.content.split("|")
                    current_count = int(parts[2].strip().replace("x", ""))
                    reported_count = current_count + 1
                    if reported_count > 3:
                        reported_count = 3  # enforce max 3 reports per member
                    new_content = f"{partner_member_id} | {reported_alias} | {reported_count}x | Reason: {reason}"
                    await last_msg.edit(content=new_content)
                else:
                    await reported_channel.send(
                        f"{partner_member_id} | {reported_alias} | {reported_count}x | Reason: {reason}")
            except Exception as e:
                print(f"[rd_report] Failed updating reported channel: {e}")

        # -------------------------------
        # Update reporter
        # -------------------------------
        reporter_count += 1
        if reporter_channel:
            try:
                last_msg = None
                async for msg in reporter_channel.history(limit=100):
                    if msg.content.split("|")[0].strip() == str(reporter.id):
                        last_msg = msg
                        break
                if last_msg:
                    parts = last_msg.content.split("|")
                    current_count = int(parts[2].strip().replace("x", ""))
                    reporter_count = current_count + 1
                    if reporter_count > 3:
                        reporter_count = 3
                    new_content = f"{reporter.id} | {reporter.display_name} | {reporter_count}x"
                    await last_msg.edit(content=new_content)
                else:
                    await reporter_channel.send(f"{reporter.id} | {reporter.display_name} | {reporter_count}x")
            except Exception as e:
                print(f"[rd_report] Failed updating reporter channel: {e}")

        # -------------------------------
        # Notify reporter
        # -------------------------------
        await ctx.send(f"✅ You reported **{reported_alias}** for: {reason} ({reported_count}/3 reports)")

        # -------------------------------
        # Auto hangup
        # -------------------------------
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

        # Get the Discord username to share
        sender_user = ctx.author
        sender_discord_tag = str(sender_user)  # This gives Username#1234

        # Get partner's webhook to send the message
        partner_webhook = partner_call_info.get("webhook")
        if not partner_webhook:
            return await ctx.send("⚠️ Cannot send friend request. Partner webhook not found.")

        try:
            # Send the "friend request" message to the partner
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
                if not call_info: continue
                last = call_info.get("last_activity", now)
                if now - last > self.idle_timeout:
                    await self._hangup_pair(gid)
                    return

    # ---------------------------
    # on_message forwarding
    # ---------------------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild or message.webhook_id is not None: return
        if not isinstance(message.channel, discord.TextChannel): return
        if "rocket-dial" not in message.channel.name.lower(): return

        guild_id = str(message.guild.id)
        if guild_id not in self.calls: return

        call_info = self.calls[guild_id]
        partner_id = call_info.get("partner")
        if not partner_id: return

        partner_info = self.calls.get(str(partner_id))
        if not partner_info: return

        target_webhook = partner_info.get("webhook")
        if not target_webhook: return

        # update last activity
        call_info["last_activity"] = asyncio.get_event_loop().time()

        alias_map = call_info.setdefault("user_aliases", {})
        alias_entry = alias_map.get(message.author.id)
        if not alias_entry:
            alias_entry = random.choice(POKEMON_GIFS)
            alias_map[message.author.id] = alias_entry

        try:
            await target_webhook.send(
                content=message.content,
                username=alias_entry["name"],
                avatar_url=alias_entry["url"]
            )
        except Exception as e:
            print(f"[RocketDial] forward message error: {e}")


# ---------------------------
# Setup
# ---------------------------
async def setup(bot: commands.Bot):
    await bot.add_cog(RocketDial(bot))
