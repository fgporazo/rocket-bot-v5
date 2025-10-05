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
        random.seed(os.urandom(8))
        result = random.triangular(low, high, random.uniform(low, high))
        return max(low, min(high, int(result)))

    async def merge_avatars(self, urls: list):
        images = []
        async with aiohttp.ClientSession() as session:
            for url in urls:
                async with session.get(url) as resp:
                    img = Image.open(io.BytesIO(await resp.read())).convert("RGBA")
                    images.append(img)

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

        # If bot involved → automatic 0%
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
    # 🎨 Color System
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
    @commands.cooldown(10, 300, commands.BucketType.user)
    async def duo(self, ctx, *members: discord.Member):
        """Villain duo compatibility check."""
        if len(members) == 0:
            return await ctx.reply("❌ Mention someone to form your villain duo!")
        if len(members) > 2:
            return await ctx.reply("❌ Too many! Use `.duo @user` or `.duo @user1 @user2`.")

        # Determine the pair
        pair = [ctx.author, members[0]] if len(members) == 1 else [members[0], members[1]]

        # Prevent self-duo
        if pair[0].id == pair[1].id:
            return await ctx.reply("❌ You can’t duo yourself, villain! Find an accomplice 😈")

        # Prevent bots
        if any(m.bot for m in pair):
            return await ctx.reply("❌ You can’t duo with bots, not even Team Rocket’s HQ systems 🤖")

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
        await award_points(self.bot, ctx.author, 2, notify_channel=ctx.channel)

    # -------------------------------------------------------
    # 💥 TRIO COMMAND
    # -------------------------------------------------------
    @commands.command()
    @commands.cooldown(10, 300, commands.BucketType.user)
    async def trio(self, ctx, *members: discord.Member):
        """Villain trio compatibility check."""
        if len(members) < 2:
            return await ctx.reply("❌ Mention at least **2 people** for a trio! Example: `.trio @user1 @user2`")
        if len(members) > 3:
            return await ctx.reply("❌ Too many villains! Max trio is 3 members.")

        # Allow self once, but not duplicates
        trio_members = list(dict.fromkeys(members))  # remove duplicates
        if ctx.author not in trio_members:
            trio_members.insert(0, ctx.author)

        # Ensure only one self
        self_count = sum(1 for m in trio_members if m.id == ctx.author.id)
        if self_count > 1:
            return await ctx.reply("❌ You can only include yourself **once**, narcissist 😈")

        # Exclude multiple bots
        bot_count = sum(1 for m in trio_members if m.bot)
        if bot_count > 1 or all(m.bot for m in trio_members):
            return await ctx.reply("❌ You can’t include multiple bots in a trio! Even Team Rocket has limits 🤖")

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
        await award_points(self.bot, ctx.author, 3, notify_channel=ctx.channel)

    # -------------------------------------------------------
    # ⏱ COOLDOWN HANDLER — No points on cooldown
    # -------------------------------------------------------
    @duo.error
    @trio.error
    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.reply(f"⏳ Slow down, villain! Try again in **{int(error.retry_after)}s**.")
        else:
            raise error


# -------------------------------------------------------
# Setup
# -------------------------------------------------------
async def setup(bot):
    await bot.add_cog(VillainShip(bot))
