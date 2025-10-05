import discord
from discord.ext import commands
import random
from PIL import Image
import aiohttp
import io
import os
from helpers import award_points

# Load admin IDs from environment variable
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()}


class VillainShip(commands.Cog):
    """💥 Team Rocket Duo & Trio Compatibility — Villain Edition"""

    def __init__(self, bot):
        self.bot = bot

        # ---------------- DUO Messages ----------------
        self.duo_messages = {
            "low": [
                "You two couldn’t even steal a Magikarp together 😂",
                "Villain duo? More like chaotic good duo. Harmless but hilarious!",
                "You tried… and then tripped over your own Pokéballs 💀",
                "Even Meowth says, 'Eh, maybe stick to karaoke instead of villainy!'",
            ],
            "medium": [
                "You two could steal snacks from Giovanni’s desk and get away with it!",
                "Half chaos, half teamwork — just enough to cause a mild explosion 💥",
                "Your evil plan was going fine… until someone pressed the self-destruct button.",
                "Jessie and James approve — but they’re still the drama kings 👑",
            ],
            "high": [
                "Giovanni is trembling… this villain duo is a certified menace 😈",
                "Your synergy could outshine Team Rocket’s entire career!",
                "The world isn’t ready for this much chaotic beauty 💋",
                "Even Arceus can’t stop your villainy now — Team Rocket salutes you! 🚀",
                "Together, you two could steal Pikachu *and* look fabulous doing it 💅",
            ],
        }

        # ---------------- TRIO Messages ----------------
        self.trio_messages = {
            "low": [
                "You three couldn’t even steal a Rattata 🐭",
                "Villains? More like confused tourists in Team Rocket uniforms 😂",
                "Even Wobbuffet refuses to join this mission 💀",
                "Your ‘evil’ plan ended in a group hug. How wholesome.",
            ],
            "medium": [
                "The trio that plans together… forgets the plan together!",
                "You’re basically the diet version of Team Rocket — fun-sized chaos!",
                "Meowth’s fur is singed again. That’s how you know it’s working 🔥",
                "You’ve got potential — just stop arguing about who gets the Pokéballs first!",
            ],
            "high": [
                "Giovanni just promoted you three to *Elite Villains* 😈",
                "The chaos is unmatched — Jessie and James are in awe!",
                "This trio could hijack a gym battle and win without even trying 💅",
                "Legends say even Mewtwo hides when your squad enters the room 👀",
                "Rocket HQ reports record-breaking villain energy detected 🚀",
            ],
        }

    # -------------------------------------------------------
    # 🔮 Utility
    # -------------------------------------------------------
    def chaotic_random(self, low: int, high: int) -> int:
        """More natural chaotic randomness using triangular distribution."""
        random.seed(os.urandom(8))
        result = random.triangular(low, high, random.uniform(low, high))
        return max(low, min(high, int(result)))

    async def merge_avatars(self, urls: list):
        """Merge avatar URLs horizontally into one image."""
        images = []
        async with aiohttp.ClientSession() as session:
            for url in urls:
                async with session.get(url) as resp:
                    img = Image.open(io.BytesIO(await resp.read())).convert("RGBA")
                    images.append(img)

        # Resize to consistent height
        height = 128
        resized = [img.resize((int(img.width * height / img.height), height)) for img in images]
        total_width = sum(img.width for img in resized)
        merged = Image.new("RGBA", (total_width, height), (255, 255, 255, 0))

        x_offset = 0
        for img in resized:
            merged.paste(img, (x_offset, 0), img)
            x_offset += img.width

        image_bytes = io.BytesIO()
        merged.save(image_bytes, format="PNG")
        image_bytes.seek(0)
        return image_bytes

    # -------------------------------------------------------
    # 🧬 Villain Percentage Logic
    # -------------------------------------------------------
    def calculate_villain_percentage(self, author, members, bot_member):
        all_ids = [m.id for m in members] + [author.id]

        # 🚫 Exclude bots (including self.bot)
        if bot_member.id in all_ids or any(m.bot for m in members):
            return 0

        author_is_admin = author.id in ADMIN_IDS
        partner_is_admin = any(mid in ADMIN_IDS for mid in all_ids if mid != author.id)
        all_admins = all(mid in ADMIN_IDS for mid in all_ids)

        if all_admins:
            return 100
        if (author_is_admin and not partner_is_admin) or (not author_is_admin and partner_is_admin):
            return self.chaotic_random(80, 100)
        if author_is_admin:
            return self.chaotic_random(80, 95)

        return self.chaotic_random(0, 100)

    # -------------------------------------------------------
    # 🎨 Embed Color System
    # -------------------------------------------------------
    def villain_color_and_emoji(self, percent: int):
        if percent == 0:
            return "🤡", discord.Color.dark_gray()
        elif percent < 40:
            return "🤡", discord.Color.blue()
        elif percent < 80:
            return "😼", discord.Color.orange()
        else:
            return "😈", discord.Color.red()

    # -------------------------------------------------------
    # 💞 DUO COMMAND
    # -------------------------------------------------------
    @commands.command()
    @commands.cooldown(1, 600, commands.BucketType.user)
    async def duo(self, ctx, *members: discord.Member):
        """Villain duo compatibility check."""
        if len(members) == 1:
            pair = [ctx.author, members[0]]
        elif len(members) == 2:
            pair = [members[0], members[1]]
        else:
            await ctx.reply("❌ Invalid usage! Use `.duo @user` or `.duo @user1 @user2`.")
            return

        # 🚫 Prevent self-duo and bot targets
        if pair[0].id == pair[1].id:
            await ctx.reply("💔 You can’t form a villain duo with yourself, silly!")
            return
        if any(m.bot for m in pair):
            await ctx.reply("🤖 Villains don’t team up with bots!")
            return

        msg = await ctx.send("⚡ Calculating villain chaos… please wait!")

        percent = self.calculate_villain_percentage(ctx.author, pair, ctx.guild.me)
        emoji, color = self.villain_color_and_emoji(percent)
        category = "low" if percent < 40 else "medium" if percent < 80 else "high"
        line = random.choice(self.duo_messages[category])

        urls = [m.display_avatar.url for m in pair]
        merged = await self.merge_avatars(urls)
        file = discord.File(fp=merged, filename="duo.png")

        embed = discord.Embed(
            title=f"{emoji} Villain Duo Compatibility — {percent}%",
            description=(
                f"{pair[0].mention} ⚡ {pair[1].mention}\n"
                f"**Villain Level:** {percent}%\n\n"
                f"🤡 Below 40% → Clumsy villains\n"
                f"😼 40–79% → Functional chaos\n"
                f"😈 80–100% → Pure evil excellence\n\n"
            ),
            color=color,
        )
        embed.add_field(name="", value=line, inline=False)
        embed.set_image(url="attachment://duo.png")

        await msg.edit(content=None, embed=embed, attachments=[file])

        # ✅ Award points only if not in cooldown
        bucket = ctx.command._buckets.get_bucket(ctx.message)
        retry_after = bucket.update_rate_limit()
        if retry_after is None:
            await award_points(self.bot, ctx.author, 5, notify_channel=ctx.channel)

    # -------------------------------------------------------
    # 💥 TRIO COMMAND
    # -------------------------------------------------------
    @commands.command()
    @commands.cooldown(1, 600, commands.BucketType.user)
    async def trio(self, ctx, *members: discord.Member):
        """Villain trio compatibility check."""
        if len(members) < 2:
            await ctx.reply("❌ Mention at least **2 people** for a trio! Example: `.trio @user1 @user2`")
            return
        elif len(members) == 2:
            trio_members = [ctx.author, members[0], members[1]]
        elif len(members) == 3:
            trio_members = list(members)
        else:
            await ctx.reply("❌ Invalid usage! You can only mention up to 3 users.")
            return

        # 🚫 Prevent duplicates, self-doubles, and bots
        unique_ids = {m.id for m in trio_members}
        if len(unique_ids) < 3:
            await ctx.reply("💔 You can’t form a trio with duplicates! No cloning allowed, villain.")
            return
        if any(m.bot for m in trio_members):
            await ctx.reply("🤖 Bots can’t join your villain squad!")
            return

        msg = await ctx.send("⚡ Assembling villain squad… chaos imminent!")

        percent = self.calculate_villain_percentage(ctx.author, trio_members, ctx.guild.me)
        emoji, color = self.villain_color_and_emoji(percent)
        category = "low" if percent < 40 else "medium" if percent < 80 else "high"
        line = random.choice(self.trio_messages[category])

        urls = [m.display_avatar.url for m in trio_members]
        merged = await self.merge_avatars(urls)
        file = discord.File(fp=merged, filename="trio.png")

        embed = discord.Embed(
            title=f"{emoji} Villain Trio Compatibility — {percent}%",
            description=(
                " ⚡ ".join(m.mention for m in trio_members)
                + f"\n**Villain Level:** {percent}%\n\n"
                  f"🤡 Below 40% → Clumsy villains\n"
                  f"😼 40–79% → Functional chaos\n"
                  f"😈 80–100% → Pure evil excellence\n\n"
            ),
            color=color,
        )
        embed.add_field(name="", value=line, inline=False)
        embed.set_image(url="attachment://trio.png")

        await msg.edit(content=None, embed=embed, attachments=[file])

        # ✅ Award points only if not in cooldown
        bucket = ctx.command._buckets.get_bucket(ctx.message)
        retry_after = bucket.update_rate_limit()
        if retry_after is None:
            await award_points(self.bot, ctx.author, 5, notify_channel=ctx.channel)

    # -------------------------------------------------------
    # ⏱ COOLDOWN HANDLER
    # -------------------------------------------------------
    @duo.error
    @trio.error
    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.CommandOnCooldown):
            mins = int(error.retry_after // 60)
            secs = int(error.retry_after % 60)
            await ctx.reply(f"⏳ Slow down, villain! Try again in **{mins}m {secs}s**.")


# -------------------------------------------------------
# Setup
# -------------------------------------------------------
async def setup(bot):
    await bot.add_cog(VillainShip(bot))
