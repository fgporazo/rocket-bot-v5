# rocket_secret.py
import os
import discord
from discord.ext import commands
import random
from datetime import datetime
import re
import asyncio
from helpers import award_points

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
    "Hey there! 🌟 Just wanted to send a little surprise your way. Hope this message brightens your day as much as you brighten everyone else’s. Keep shining and having fun! 💫",
    "Hello, friend! 🚀 Here’s a secret note from someone thinking of you. May it bring a smile, a laugh, or just a little mystery to your day. Team Rocket approves! 😉✨",
    "Surprise! 🎉 A little message is zooming your way with positive vibes. Whether it’s a greeting, a confession, or a postcard, it’s all meant for you. Enjoy every bit of it! 💌",
    "Greetings, superstar! 🌠 Here’s a secret message just for you. May it make your day a bit more magical and full of wonder. Keep being amazing! 💖",
    "Psst… something fun is happening! 💫 A secret note has been launched just for you. Whether it’s a love letter, a postcard, or just a hello, it comes with lots of Rocket energy! 🚀",
    "Hello! 🖼️ This little message comes wrapped in mystery and excitement. It’s meant to make you smile, think, or just feel a little special today. Enjoy this surprise! ✨",
    "Hey! 💌 Someone wanted to send you a message without revealing themselves. It could be a confession, a greeting, or a playful note — but it’s all for you! 💫",
    "Surprise incoming! 📩 This note is filled with mystery, joy, and a little sparkle. May it brighten your day or inspire a laugh. Team Rocket sends their best! 🌟"
]

ROCKET_ANNOUNCEMENTS = [
    "🌌 Prepare for trouble… 💥 A secret transmission has been launched! 💌 Someone’s heart is blasting off with a message! 🚀✨",
    "🚨 And make it double… 💌 Team Rocket has intercepted a signal! Someone’s sending a secret message! 💖💫",
    "✨ Love is blasting off again! 💌 A hidden admirer just fired up their rocket boosters! 🌠🔥",
    "🔥 An anonymous message has been launched… 💌 Brace yourselves! 💫💘",
    "🌠 Pssst! Someone’s shooting for the stars with a secret message 💌 Stay tuned! 🚀💖"
]

GIFS = [
    "https://i.pinimg.com/originals/85/fa/e9/85fae9a8a1107a4588b12c845689f534.gif",
    "https://64.media.tumblr.com/2a3d436fe8618916c4ace07cd7f1f7f8/tumblr_oxd33aNLVw1w6drx7o1_500.gif",
    "https://media3.giphy.com/media/v1.Y2lkPTc5MGI3NjExeGw2bzhhNm5qMTNyazd3ejY4aXA1c3hnMjd2Mnp3cDF0ZHM3MDZ3OSZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/z90q62V3rnNuw/giphy.gif",
    "https://media.tenor.com/-RZCWGnYDIQAAAAM/narcissist-jessie.gif",
    "https://pa1.aminoapps.com/6331/acc96e0f5c2fae2aaed478df2c5d4597245bad90_00.gif"
]

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp")

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

def extract_image_url_from_text(text: str) -> str | None:
    # Search for any URL ending with valid image extension
    urls = re.findall(r"https?://\S+", text)
    for url in urls:
        if url.lower().endswith(IMAGE_EXTENSIONS):
            return url
    return None

# ----------------------
# Secret Admirer Cog
# ----------------------
class SecretAdmirer(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ----------------------
    # Main command group
    # ----------------------
    @commands.group(name="secret", invoke_without_command=True)
    async def secret(self, ctx):
        if isinstance(ctx.channel, discord.DMChannel):
            return await ctx.send("⚠️ Try `.secret start` here in DM to begin.")

        sessions[ctx.author.id] = ctx.guild.id
        try:
            await ctx.author.send(
                "👋 Hi! This is Team Rocket.\n"
                "You’re about to message anonymously. Yay!\n\n"
                "👉 Type `.secret start` here in DM to begin.\n"
                "👉 Or use `.secret custom <message>` to send your own custom message directly.\n"
                f"📎 You can attach 1 image or GIF.\n⚠️ Maximum {MAX_WORDS} words per message."
            )

            text = random.choice(ROCKET_ANNOUNCEMENTS)
            gif = random.choice(GIFS)
            embed = discord.Embed(description=text, color=discord.Color.magenta())
            embed.set_thumbnail(url=gif)

            await ctx.send(content="@everyone", embed=embed, allowed_mentions=discord.AllowedMentions(everyone=True))
        except discord.Forbidden:
            await ctx.send("⚠️ I can’t DM you. Please enable DMs and try again.")

    # ----------------------
    # Start DM flow
    # ----------------------
    @secret.command(name="start")
    async def secret_start(self, ctx):
        if not isinstance(ctx.channel, discord.DMChannel):
            return await ctx.send("⚠️ Please use `.secret start` in DM.")

        last = user_cooldowns.get(ctx.author.id)
        if last and (datetime.utcnow() - last).total_seconds() < COOLDOWN_SECONDS:
            return await ctx.send("⚠️ Please wait a bit before starting another message.")

        if not can_send_today(ctx.author.id):
            return await ctx.send(f"⚠️ You’ve reached your daily limit of {MAX_DAILY} Secret Admirer messages. Try again tomorrow.")

        guild_id = sessions.get(ctx.author.id)
        if not guild_id:
            mutuals = [g for g in self.bot.guilds if g.get_member(ctx.author.id)]
            if not mutuals:
                return await ctx.send("⚠️ Go to the Secret channel and click the Send Notes button to get started.")
            guild_id = mutuals[0].id
            sessions[ctx.author.id] = guild_id

        user_cooldowns[ctx.author.id] = datetime.utcnow()
        increment_daily(ctx.author.id)

        await self.send_flow_start(ctx)

    # ----------------------
    # Flow start view
    # ----------------------
    async def send_flow_start(self, ctx):
        view = discord.ui.View()

        async def help_callback(interaction: discord.Interaction):
            await interaction.response.send_message("✨ Team Rocket will help you craft a message!", ephemeral=True)
            confession = random.choice(CONFESSIONS)
            await self.choose_title(ctx, confession)

        async def own_callback(interaction: discord.Interaction):
            await interaction.response.send_message(
                "✏️ Okay! Let’s craft your custom message.", ephemeral=True
            )
            await self.prompt_custom_message(ctx)

        help_btn = discord.ui.Button(label="Let Team Rocket Help 🎲", style=discord.ButtonStyle.primary)
        own_btn = discord.ui.Button(label="Make My Own Message ✏️", style=discord.ButtonStyle.success)
        help_btn.callback = help_callback
        own_btn.callback = own_callback
        view.add_item(help_btn)
        view.add_item(own_btn)

        await ctx.send("Do you want Team Rocket to help you, or write your own message?", view=view)

    # ----------------------
    # Prompt custom message
    # ----------------------
    async def prompt_custom_message(self, ctx):
        await ctx.send(
            f"✏️ Type your custom message now (or attach 1 image/GIF).\n⚠️ Max {MAX_WORDS} words, {MAX_SIZE_MB}MB."
        )

        def check(m):
            return m.author == ctx.author and isinstance(m.channel, discord.DMChannel)

        try:
            reply = await self.bot.wait_for("message", check=check, timeout=180)
        except asyncio.TimeoutError:
            return await ctx.send("⏰ Timeout. Please start again with `.secret start`.")

        message_text = reply.content.strip() if reply.content else "[Image only]"
        image_url = None

        # Attachments take priority
        if reply.attachments:
            attachment = reply.attachments[0]
            if attachment.content_type not in ALLOWED_TYPES:
                return await ctx.send("⚠️ Only image files (jpg, png, gif, webp) are allowed.")
            if attachment.size > MAX_SIZE_MB * 1024 * 1024:
                return await ctx.send(f"⚠️ File too large. Maximum allowed is {MAX_SIZE_MB} MB.")
            image_url = attachment.url
        else:
            # Check for any image URL in message
            found_url = extract_image_url_from_text(message_text)
            if found_url:
                image_url = found_url
                # Remove URL from text if it's the only thing
                if message_text.strip() == found_url:
                    message_text = "[Image only]"

        if message_text != "[Image only]":
            word_count = len(re.findall(r'\S+', message_text))
            if word_count > MAX_WORDS:
                return await ctx.send(f"⚠️ Your message is too long! Max {MAX_WORDS} words.")

        await self.choose_title(ctx, message_text, image_url=image_url)

    # ----------------------
    # Choose title
    # ----------------------
    async def choose_title(self, ctx, message_text, image_url=None):
        view = discord.ui.View()
        titles = {
            "💌 Love Letter": "💌 Love Letter 💌",
            "🖼️ Post Card": "🖼️ Post Card 🖼️",
            "📩 Confession": "📩 Confession 📩",
            "📨 Greetings": "📨 Greetings 📨"
        }

        for emoji_label, title_name in titles.items():
            async def make_callback(interaction: discord.Interaction, title=title_name):
                await interaction.response.send_message(f"📜 You chose **{title}**!", ephemeral=True)
                await self.ask_receiver(ctx, message_text, image_url=image_url, embed_title=title)
            btn = discord.ui.Button(label=emoji_label, style=discord.ButtonStyle.secondary)
            btn.callback = make_callback
            view.add_item(btn)

        await ctx.send("Choose a title for your message:", view=view)

    # ----------------------
    # Secret confess command (DM)
    # ----------------------
    @secret.command(name="custom")
    async def secret_custom(self, ctx, *, message: str = None):
        if not isinstance(ctx.channel, discord.DMChannel):
            return await ctx.send("⚠️ Please use this in DM.")

        last = user_cooldowns.get(ctx.author.id)
        if last and (datetime.utcnow() - last).total_seconds() < COOLDOWN_SECONDS:
            return await ctx.send("⚠️ Please wait a bit before sending another message.")

        if not can_send_today(ctx.author.id):
            return await ctx.send(f"⚠️ You’ve reached your daily limit of {MAX_DAILY} messages. Try again tomorrow.")

        if ctx.author.id not in sessions:
            return await ctx.send("⚠️ Go to the Secret channel and click the Secret Notes button to get started.")

        image_url = None

        # Attachment takes priority
        if ctx.message.attachments:
            attachment = ctx.message.attachments[0]
            if attachment.content_type not in ALLOWED_TYPES:
                return await ctx.send("⚠️ Only image files (jpg, png, gif, webp) are allowed.")
            if attachment.size > MAX_SIZE_MB * 1024 * 1024:
                return await ctx.send(f"⚠️ File too large. Maximum allowed is {MAX_SIZE_MB} MB.")
            image_url = attachment.url

        # Extract image URL from message anywhere
        if message:
            found_url = extract_image_url_from_text(message)
            if found_url:
                image_url = found_url
                if message.strip() == found_url:
                    message = "[Image only]"

            word_count = len(re.findall(r'\S+', message))
            if word_count > MAX_WORDS:
                return await ctx.send(f"⚠️ Your message is too long! Max {MAX_WORDS} words.")

        if not message and not image_url:
            return await ctx.send("⚠️ You need to provide a message or attach an image/GIF.")

        user_cooldowns[ctx.author.id] = datetime.utcnow()
        increment_daily(ctx.author.id)

        await self.choose_title(ctx, message if message else "[Image only]", image_url=image_url)

    # ----------------------
    # Ask receiver
    # ----------------------
    async def ask_receiver(self, ctx, message_text, image_url=None, embed_title="💌 Secret Note 💌"):
        await ctx.send("💌 Who should receive your secret message? Mention them, or type `skip` to send it anonymously.")

        def check(m):
            return m.author == ctx.author and isinstance(m.channel, discord.DMChannel)

        try:
            reply = await self.bot.wait_for("message", check=check, timeout=60)
        except asyncio.TimeoutError:
            return await ctx.send("⏰ Timeout. Please start again with `.secret start`.")

        receiver = reply.content if reply.content.lower() != "skip" else "***Secret***"
        await self.final_announcement(ctx, receiver, message_text, image_url=image_url, embed_title=embed_title)

    # ----------------------
    # Final announcement
    # ----------------------
    async def final_announcement(self, ctx, receiver, message_text, image_url=None, embed_title="💌 Secret Note 💌"):
        guild_id = sessions.get(ctx.author.id)
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return await ctx.send("⚠️ Could not find the server session. Try `.secret` again.")

        channel = guild.get_channel(SECRET_ADMIRER_CHANNEL_ID)
        if not channel:
            return await ctx.send("⚠️ Secret channel not found. Please check configuration.")

        embed = discord.Embed(title=embed_title, description=f"***Dear*** {receiver}\n\n*{message_text}*", color=discord.Color.pink())
        if image_url:
            embed.set_thumbnail(url=image_url)
        else:
            embed.set_thumbnail(url=random.choice(GIFS))

        await channel.send(embed=embed)

        await ctx.send(f"✅ Your message has been sent anonymously to {channel.mention}!\n💫 Check it out there!")

        try:
            reward_amount = 55
            await ctx.author.send(f"🎉 Congratulations! You’ve earned ** 💎 {reward_amount} gems** for bravely sending a Secret Message 💖🚀")
            await award_points(self.bot, ctx.author, reward_amount, dm=True)
        except discord.Forbidden:
            print(f"[WARN] Could not DM user {ctx.author.id} their gem reward.")

        del sessions[ctx.author.id]

# ----------------------
# Setup
# ----------------------
async def setup(bot):
    await bot.add_cog(SecretAdmirer(bot))
