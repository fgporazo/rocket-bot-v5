# rocket_dial.py
import discord
from discord.ext import commands
import asyncio
import random
import json
import os
from typing import Dict, Optional, Tuple, Any

DIAL_FILE = "rocket_dial_connections.json"
VOICEMAIL_FILE = "rocket_dial_voicemails.json"

# Pokémon GIFs (name + gif url)
POKEMON_GIFS = [
    {"name": "Pikachu", "url": "https://i.pinimg.com/originals/8a/81/ec/8a81ecd8fdd266b3221da325875c0ea.gif"},
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

def load_json_file(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def save_json_file(path: str, data: Dict[str, Any]):
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass

class RocketDial(commands.Cog):
    """🚀 Rocket Dial — webhook-based cross-server dial with Pokémon disguises."""

    def __init__(self, bot):
        self.bot = bot
        self.active_pairs: Dict[str, str] = load_json_file(DIAL_FILE)
        self.calls: Dict[str, Dict[str, Any]] = {}
        self.waiting_call: Optional[Tuple[int, discord.TextChannel, discord.Webhook]] = None
        self.call_timeout = 300  # 5 minutes
        self.voicemails: Dict[str, list] = load_json_file(VOICEMAIL_FILE)

    # ---------------------------
    # Utilities
    # ---------------------------
    def find_dial_channel(self, guild: discord.Guild) -> Optional[discord.TextChannel]:
        for ch in guild.text_channels:
            if "rocket-dial" in ch.name.lower():
                return ch
        return None

    def pick_two_unique_aliases(self) -> Tuple[Dict[str, str], Dict[str, str]]:
        a, b = random.sample(POKEMON_GIFS, 2)
        return ({"name": a["name"], "gif": a["url"]}, {"name": b["name"], "gif": b["url"]})

    async def create_channel_webhook(self, channel: discord.TextChannel, webhook_name: str = "RocketDial-Web") -> Optional[discord.Webhook]:
        try:
            wh = await channel.create_webhook(name=webhook_name)
            return wh
        except discord.Forbidden:
            return None
        except Exception:
            return None

    async def delete_webhook_safe(self, webhook: discord.Webhook):
        try:
            await webhook.delete()
        except Exception:
            pass

    def persist_pairs(self):
        save_json_file(DIAL_FILE, self.active_pairs)
        save_json_file(VOICEMAIL_FILE, self.voicemails)

    # ---------------------------
    # Commands group
    # ---------------------------
    @commands.group(name="rd", invoke_without_command=True, help="Rocket Dial command guide")
    async def rd(self, ctx: commands.Context):
        lines = [
            "`.rd call` or `.rdc` — Start a Rocket Dial call to another server",
            "`.rd hangup` or `.rdh` — End the current Rocket Dial call",
            "`.rd inbox` — Check saved Rocket Dial messages",
            "`.rd reveal` or `.rdr` — Reveal your real identity to the other server",
            "`.rd` — Show this command guide",
        ]
        tip = "💡 Tip: The dial ends automatically after **5 minutes** if no one answers."
        msg = "📖 **Rocket Dial Commands**\n" + "\n".join(lines) + f"\n\n{tip}"
        await ctx.send(msg)

    @commands.command(name="rdc", help="Shortcut for .rd call")
    async def rdc(self, ctx: commands.Context):
        await ctx.invoke(self.bot.get_command("rd call"))

    @commands.command(name="rdh", help="Shortcut for .rd hangup")
    async def rdh(self, ctx: commands.Context):
        await ctx.invoke(self.bot.get_command("rd hangup"))

    # ---------------------------
    # .rd call
    # ---------------------------
    @rd.command(name="call", help="Start a Rocket Dial call")
    async def rd_call(self, ctx: commands.Context):
        if not isinstance(ctx.channel, discord.TextChannel) or "rocket-dial" not in ctx.channel.name.lower():
            return await ctx.send("⚠️ Please run this command inside a channel with `rocket-dial` in its name.")

        guild_id = str(ctx.guild.id)
        if guild_id in self.active_pairs or guild_id in self.calls:
            return await ctx.send("📞 Your server is already in a Rocket Dial call. Use `.rd hangup` to end it first.")

        webhook = await self.create_channel_webhook(ctx.channel, webhook_name=f"RocketDial-{ctx.guild.name[:20]}")
        if webhook is None:
            return await ctx.send("⚠️ I need 'Manage Webhooks' permission to start Rocket Dial.")

        # Connect if waiting server exists
        if self.waiting_call and self.waiting_call[0] != ctx.guild.id:
            waiting_guild_id, waiting_channel, waiting_webhook = self.waiting_call
            self.waiting_call = None

            alias_a, alias_b = self.pick_two_unique_aliases()
            self.calls[guild_id] = {"partner": str(waiting_guild_id), "webhook": webhook, "alias": alias_a, "real_user": ctx.author, "revealed": False}
            self.calls[str(waiting_guild_id)] = {"partner": guild_id, "webhook": waiting_webhook, "alias": alias_b, "real_user": None, "revealed": False}

            self.active_pairs[guild_id] = str(waiting_guild_id)
            self.active_pairs[str(waiting_guild_id)] = guild_id
            self.persist_pairs()

            await ctx.send(f"📡 **Call connected!** You are speaking as **{alias_a['name']}**.")
            await waiting_channel.send(f"📡 **Call connected!** You are speaking as **{alias_b['name']}**.")
            return

        # Otherwise, mark as waiting
        self.waiting_call = (ctx.guild.id, ctx.channel, webhook)
        await ctx.send(
            "☎️ **Dialing another Rocket server...**\n"
            "💡 Tip: The dial ends automatically after **5 minutes** if no one answers.\n"
            "_You can leave a message when the dial times out._"
        )

        try:
            remaining = self.call_timeout
            while remaining > 0:
                await asyncio.sleep(60)
                remaining -= 60
                if not self.waiting_call or self.waiting_call[0] != ctx.guild.id:
                    return
                minutes_left = max(0, remaining // 60)
                await ctx.send(f"⏳ Waiting... **{minutes_left} minute(s)** left before the call ends.")

            if self.waiting_call and self.waiting_call[0] == ctx.guild.id:
                _, waiting_channel, waiting_webhook = self.waiting_call
                self.waiting_call = None
                try:
                    await waiting_webhook.delete()
                except Exception:
                    pass

                await ctx.send("📴 No one picked up. The Rocket Dial call has been terminated.")
                await ctx.send("💬 You can leave a message below. Type your message within 60 seconds:")

                def check(m: discord.Message):
                    return m.author == ctx.author and m.channel == ctx.channel

                try:
                    voicemail = await self.bot.wait_for("message", timeout=60.0, check=check)
                    self.voicemails.setdefault(guild_id, []).append({
                        "author": str(ctx.author.id),
                        "content": voicemail.content,
                        "channel_name": ctx.channel.name
                    })
                    self.persist_pairs()
                    await ctx.send("📨 Message saved!")
                except asyncio.TimeoutError:
                    await ctx.send("⌛ Time’s up! No message recorded.")
        except asyncio.CancelledError:
            self.waiting_call = None
            return

    # ---------------------------
    # .rd hangup
    # ---------------------------
    @rd.command(name="hangup", help="End current Rocket Dial call")
    async def rd_hangup(self, ctx: commands.Context):
        guild_id = str(ctx.guild.id)

        if self.waiting_call and self.waiting_call[0] == ctx.guild.id:
            _, waiting_channel, waiting_webhook = self.waiting_call
            self.waiting_call = None
            try:
                await waiting_webhook.delete()
            except Exception:
                pass
            return await ctx.send("📴 Call canceled before connection.")

        if guild_id not in self.calls and guild_id not in self.active_pairs:
            return await ctx.send("📴 You are not in an active Rocket Dial call.")

        partner_id = None
        if guild_id in self.calls:
            partner_id = self.calls[guild_id]["partner"]
        elif guild_id in self.active_pairs:
            partner_id = self.active_pairs.get(guild_id)

        # cleanup both sides
        try:
            if guild_id in self.calls:
                wh = self.calls[guild_id].get("webhook")
                if wh:
                    try:
                        await wh.delete()
                    except Exception:
                        pass
                self.calls.pop(guild_id, None)
            if partner_id and partner_id in self.calls:
                partner_wh = self.calls[partner_id].get("webhook")
                if partner_wh:
                    try:
                        await partner_wh.delete()
                    except Exception:
                        pass
                self.calls.pop(partner_id, None)
        except Exception:
            pass

        if guild_id in self.active_pairs:
            other = self.active_pairs.pop(guild_id, None)
            if other:
                self.active_pairs.pop(str(other), None)
            self.persist_pairs()

        try:
            if partner_id:
                partner_guild = self.bot.get_guild(int(partner_id))
                if partner_guild:
                    partner_chan = self.find_dial_channel(partner_guild)
                    if partner_chan:
                        await partner_chan.send("📴 The other side hung up. The call has ended.")
        except Exception:
            pass

        await ctx.send("📞 You hung up the Rocket Dial call. Call ended.")

    # ---------------------------
    # .rd reveal
    # ---------------------------
    @rd.command(name="reveal", help="Reveal your real identity to the other server")
    async def rd_reveal(self, ctx: commands.Context):
        guild_id = str(ctx.guild.id)
        if guild_id not in self.calls:
            return await ctx.send("⚠️ You are not in an active Rocket Dial call.")

        call_info = self.calls[guild_id]
        if call_info.get("revealed"):
            return await ctx.send("⚠️ You have already revealed your identity.")

        call_info["revealed"] = True
        call_info["real_user"] = ctx.author  # mark the real caller

        partner_id = call_info["partner"]
        partner_guild = self.bot.get_guild(int(partner_id))
        if not partner_guild:
            return await ctx.send("⚠️ Could not find partner server.")

        partner_chan = self.find_dial_channel(partner_guild)
        if not partner_chan:
            return await ctx.send("⚠️ Could not find Rocket Dial channel in partner server.")

        # announce to partner
        await partner_chan.send(
            f"🚨 Reveal! {ctx.author.display_name} is the real caller now!",
            username=ctx.author.display_name,
            avatar_url=ctx.author.avatar.url if ctx.author.avatar else None
        )

        await ctx.send("✅ Your identity has been revealed to the other server.")

    # ---------------------------
    # Relay messages using webhooks
    # ---------------------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild or not isinstance(message.channel, discord.TextChannel):
            return
        if message.webhook_id is not None:
            return
        if "rocket-dial" not in message.channel.name.lower():
            return

        guild_id = str(message.guild.id)
        if guild_id not in self.calls:
            return

        call_info = self.calls[guild_id]
        partner_id = call_info["partner"]
        partner_guild = self.bot.get_guild(int(partner_id)) if partner_id else None
        if not partner_guild:
            return

        partner_chan = self.find_dial_channel(partner_guild)
        if not partner_chan:
            return

        partner_call = self.calls.get(str(partner_id))
        if not partner_call:
            return

        target_webhook = partner_call.get("webhook")
        alias = call_info.get("alias") or random.choice(POKEMON_GIFS)

        # Determine username/avatar based on reveal
        if call_info.get("revealed") and call_info.get("real_user"):
            username = call_info["real_user"].display_name
            avatar = call_info["real_user"].avatar.url if call_info["real_user"].avatar else None
        else:
            username = alias["name"]
            avatar = alias["gif"]

        content = message.content or ""
        for att in message.attachments:
            content += f"\n{att.url}"

        try:
            await target_webhook.send(content=content or "‎", username=username, avatar_url=avatar, wait=True)
        except Exception:
            embed = discord.Embed(description=content or " ", color=discord.Color.blurple())
            embed.set_author(name=username)
            embed.set_footer(text="Rocket Dial")
            try:
                await partner_chan.send(embed=embed)
            except Exception:
                pass

    # ---------------------------
    # .rd inbox
    # ---------------------------
    @rd.command(name="inbox", help="Show saved Rocket Dial voicemails for this server")
    async def rdinbox(self, ctx: commands.Context):
        guild_id = str(ctx.guild.id)
        items = self.voicemails.get(guild_id, [])
        if not items:
            return await ctx.send("📭 No voicemails for this server.")
        lines = []
        for i, item in enumerate(items[-10:], start=1):
            lines.append(f"{i}. {item['content']} (left by <@{item['author']}>)")
        await ctx.send("📭 Recent voicemails:\n" + "\n".join(lines))

    # ---------------------------
    # Cleanup on cog unload / bot shutdown
    # ---------------------------
    async def cog_unload(self):
        for info in list(self.calls.values()):
            wh = info.get("webhook")
            try:
                if wh:
                    await wh.delete()
            except Exception:
                pass
        if self.waiting_call:
            try:
                await self.waiting_call[2].delete()
            except Exception:
                pass

async def setup(bot):
    await bot.add_cog(RocketDial(bot))
