# rocket_secret_admirer.py
import os
import discord
from discord.ext import commands
import random
from datetime import datetime
import re
from helpers import (award_points)
# ----------------------
# Config / Environment
# ----------------------
SECRET_ADMIRER_CHANNEL_ID = int(os.getenv("SECRET_ADMIRER_CHANNEL_ID", 0))

COOLDOWN_SECONDS = 60  # 1 minute between confessions
MAX_DAILY = 3  # max confessions per day
MAX_SIZE_MB = 5  # max attachment size
ALLOWED_TYPES = ["image/jpeg", "image/png", "image/gif", "image/webp"]
MAX_WORDS = 500

sessions = {}  # {user_id: guild_id}
user_cooldowns = {}  # {user_id: datetime of last confession}
user_daily_count = {}  # {user_id: {"count": int, "date": "YYYY-MM-DD"}}

CONFESSIONS = [
    "You light up my Pokéworld like a Shiny encounter. ✨",
    "Every time I see you, my heart uses Quick Attack. 💓",
    "You're rarer than a Mew under a truck. 😉",
    "I Pikachu every time you walk by. ⚡",
    "Are you a Master Ball? Because you’ve caught my heart! 💖",
]

ROCKET_ANNOUNCEMENTS = [
    "🌌 Prepare for trouble… 💥 A secret transmission has been launched! 💌 Someone’s heart is blasting off in a Secret Admirer confession! 🚀✨",
    "🚨 And make it double… 💌 Team Rocket has intercepted a love signal! Someone’s confessing anonymously! 💖💫",
    "✨ Love is blasting off again! 💌 A hidden admirer just fired up their rocket boosters! 🌠🔥",
    "🔥 An anonymous love blast has been launched with Secret Admirer… 💌 Brace yourselves! 💫💘",
    "🌠 Pssst! Someone’s shooting for the stars with a Secret Admirer confession 💌 Stay tuned! 🚀💖"
]

GIFS = [
    "https://i.pinimg.com/originals/85/fa/e9/85fae9a8a1107a4588b12c845689f534.gif",
    "https://64.media.tumblr.com/2a3d436fe8618916c4ace07cd7f1f7f8/tumblr_oxd33aNLVw1w6drx7o1_500.gif",
    "https://media3.giphy.com/media/v1.Y2lkPTc5MGI3NjExeGw2bzhhNm5qMTNyazd3ejY4aXA1c3hnMjd2Mnp3cDF0ZHM3MDZ3OSZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/z90q62V3rnNuw/giphy.gif",
    "https://media.tenor.com/-RZCWGnYDIQAAAAM/narcissist-jessie.gif",
    "https://pa1.aminoapps.com/6331/acc96e0f5c2fae2aaed478df2c5d4597245bad90_00.gif"
]

# ----------------------
# Helper Functions
# ----------------------
def can_send_today(user_id: int) -> bool:
    today = datetime.utcnow().date().isoformat()
    data = user_daily_count.get(user_id)
    if not data or data["date"] != today:
        user_daily_count[user_id] = {"count": 0, "date": today}
        return True
    return data["count"] < MAX_DAILY

def increment_daily(user_id: int):
    user_daily_count[user_id]["count"] += 1

# ----------------------
# Secret Admirer Cog
# ----------------------
class SecretAdmirer(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.group(name="sa", invoke_without_command=True)
    async def sa(self, ctx):
        """Kick off DM flow from server."""
        if isinstance(ctx.channel, discord.DMChannel):
            return await ctx.send("⚠️ Try `.sa start` here in DM to begin.")

        sessions[ctx.author.id] = ctx.guild.id
        try:
            await ctx.author.send(
                "👋 Hi! This is Team Rocket.\n"
                "You’re about to confess anonymously. Yay!\n\n"
                "👉 Type `.sa start` here in DM to begin.\n"
                "👉 Or use `.sa confess <message>` to send your own custom confession directly.\n"
                f"📎 You can attach 1 image or GIF.\n⚠️ Maximum {MAX_WORDS} words per message."
            )

            text = random.choice(ROCKET_ANNOUNCEMENTS)
            gif = random.choice(GIFS)
            embed = discord.Embed(description=text, color=discord.Color.magenta())
            embed.set_image(url=gif)

            await ctx.send(
                content="@everyone",
                embed=embed,
                allowed_mentions=discord.AllowedMentions(everyone=True)
            )

        except discord.Forbidden:
            await ctx.send("⚠️ I can’t DM you. Please enable DMs and try again.")

    @sa.command(name="start")
    async def sa_start(self, ctx):
        if not isinstance(ctx.channel, discord.DMChannel):
            return await ctx.send("⚠️ Please use `.sa start` in DM.")

        last = user_cooldowns.get(ctx.author.id)
        if last and (datetime.utcnow() - last).total_seconds() < COOLDOWN_SECONDS:
            return await ctx.send("⚠️ Please wait a bit before starting another confession.")

        if not can_send_today(ctx.author.id):
            return await ctx.send(f"⚠️ You’ve reached your daily limit of {MAX_DAILY} Secret Admirer messages. Try again tomorrow.")

        guild_id = sessions.get(ctx.author.id)
        if not guild_id:
            mutuals = [g for g in self.bot.guilds if g.get_member(ctx.author.id)]
            if not mutuals:
                return await ctx.send("⚠️ Go to the RocketBot channel and click the Secret Admirer button to get started.")
            guild_id = mutuals[0].id
            sessions[ctx.author.id] = guild_id

        user_cooldowns[ctx.author.id] = datetime.utcnow()
        increment_daily(ctx.author.id)
        await self.send_flow_start(ctx)

    async def send_flow_start(self, ctx):
        view = discord.ui.View()

        async def help_callback(interaction: discord.Interaction):
            await interaction.response.send_message("✨ Team Rocket will help you craft a message!", ephemeral=True)
            confession = random.choice(CONFESSIONS)
            await self.ask_receiver(ctx, confession)

        async def own_callback(interaction: discord.Interaction):
            await interaction.response.send_message(
                f"✏️ Use `.sa confess <your message>` here in DM to send your custom confession.\n📎 You can attach 1 image or GIF.\n⚠️ Maximum {MAX_WORDS} words per message.",
                ephemeral=True
            )

        help_btn = discord.ui.Button(label="Let Team Rocket Help 🎲", style=discord.ButtonStyle.primary)
        own_btn = discord.ui.Button(label="Make My Own Message ✏️", style=discord.ButtonStyle.success)
        help_btn.callback = help_callback
        own_btn.callback = own_callback
        view.add_item(help_btn)
        view.add_item(own_btn)

        await ctx.send("Do you want Team Rocket to help you, or write your own confession?", view=view)

    @sa.command(name="confess")
    async def sa_confess(self, ctx, *, message: str = None):
        """Send a custom confession directly from DM, optionally with 1 image."""
        if not isinstance(ctx.channel, discord.DMChannel):
            return await ctx.send("⚠️ Please use this in DM.")

        last = user_cooldowns.get(ctx.author.id)
        if last and (datetime.utcnow() - last).total_seconds() < COOLDOWN_SECONDS:
            return await ctx.send("⚠️ Please wait a bit before sending another confession.")

        if not can_send_today(ctx.author.id):
            return await ctx.send(f"⚠️ You’ve reached your daily limit of {MAX_DAILY} Secret Admirer messages. Try again tomorrow.")

        if ctx.author.id not in sessions:
            return await ctx.send("⚠️ Go to the RocketBot channel and click the Secret Admirer button to get started.")

        image_url = None
        if ctx.message.attachments:
            attachment = ctx.message.attachments[0]
            if attachment.content_type not in ALLOWED_TYPES:
                return await ctx.send("⚠️ Only image files (jpg, png, gif, webp) are allowed.")
            if attachment.size > MAX_SIZE_MB * 1024 * 1024:
                return await ctx.send(f"⚠️ File too large. Maximum allowed is {MAX_SIZE_MB} MB.")
            image_url = attachment.url

        if message:
            word_count = len(re.findall(r'\S+', message))
            if word_count > MAX_WORDS:
                return await ctx.send(f"⚠️ Your confession is too long! Maximum allowed is {MAX_WORDS} words. Please shorten your message.")

        if not message and not image_url:
            return await ctx.send("⚠️ You need to provide a message or attach an image/GIF.")

        user_cooldowns[ctx.author.id] = datetime.utcnow()
        increment_daily(ctx.author.id)

        final_content = message if message else "[Image only]"
        await self.ask_receiver(ctx, final_content, image_url=image_url)

    async def ask_receiver(self, ctx, message_text, image_url=None):
        await ctx.send("💌 Who do you want to confess to? Mention them, or type `skip` to leave it anonymous.")

        def check(m):
            return m.author == ctx.author and isinstance(m.channel, discord.DMChannel)

        try:
            reply = await self.bot.wait_for("message", check=check, timeout=60)
        except:
            return await ctx.send("⏰ Timeout. Please start again with `.sa start`.")

        receiver = reply.content if reply.content.lower() != "skip" else "Someone special"
        await self.final_announcement(ctx, receiver, message_text, image_url=image_url)

    async def final_announcement(self, ctx, receiver, message_text, image_url=None):
        guild_id = sessions.get(ctx.author.id)
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return await ctx.send("⚠️ Could not find the server session. Try `.sa` again from the server.")

        channel = guild.get_channel(SECRET_ADMIRER_CHANNEL_ID)
        if not channel:
            return await ctx.send("⚠️ Secret Admirer channel not found. Please check the configuration.")

        embed = discord.Embed(
            title="💌 Secret Admirer Confession 💌",
            description=f"**To:** {receiver}\n\n**Message:** {message_text}",
            color=discord.Color.pink()
        )

        if image_url:
            embed.set_image(url=image_url)
        else:
            embed.set_image(url=random.choice(GIFS))

        # Public announcement in the confession channel
        await channel.send(embed=embed)

        # DM confirmation
        await ctx.send(
            f"✅ Your confession has been sent anonymously to {channel.mention}!\n"
            f"💫 Check it out there!"
        )

        # 🎁 Award gems to the sender
        try:
            reward_amount = 30
            await ctx.author.send(
                f"🎉 Congratulations, PokeCandidate! You’ve earned ** 💎 {reward_amount}  gems** "
                f"for bravely sending a Secret Admirer confession 💖🚀"
            )
            await award_points(self.bot, ctx.author, reward_amount, dm=True)

        except discord.Forbidden:
            print(f"[WARN] Could not DM user {ctx.author.id} their gem reward.")

        # End the session
        del sessions[ctx.author.id]

# ----------------------
# Setup
# ----------------------
async def setup(bot):
    await bot.add_cog(SecretAdmirer(bot))
