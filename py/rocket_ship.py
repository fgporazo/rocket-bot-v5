import discord
from discord.ext import commands
import random
from PIL import Image
import aiohttp
import io
import os
from helpers import award_points

# Read admin IDs from environment variable
ADMIN_IDS = set(int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip())

class VillainShip(commands.Cog):
    """Duo and Trio villain ships, Team Rocket style!"""

    def __init__(self, bot):
        self.bot = bot
        self.duo_messages = [
            "Together, you could steal all the rarest Pokémon and still have time for tea!",
            "Jessie and James are taking notes—this chaos duo is unstoppable!",
            "Plotting world domination? More like plotting to trip over your own tails 😂",
            "Your villainous synergy is so strong, even Meowth is shook!"
        ]

        self.trio_messages = [
            "This trio could take over the Pokémon world… if they stop arguing about snacks!",
            "Meowth approves… but only if you bring him glittery hats ✨",
            "Even Giovanni would pause his evil plans just to watch your chaos unfold!",
            "Warning: Chaos and mischief levels off the charts—catch fire extinguishers ready!"
        ]

    # -------------------------------------------------------
    # Utility
    # -------------------------------------------------------
    def generate_percentage(self, low=1, high=100):
        return random.randint(low, high)

    async def merge_avatars(self, urls: list):
        """Merge multiple avatar URLs horizontally and return a BytesIO image."""
        images = []
        async with aiohttp.ClientSession() as session:
            for url in urls:
                async with session.get(url) as resp:
                    img = Image.open(io.BytesIO(await resp.read())).convert("RGBA")
                    images.append(img)

        height = 128
        resized = [img.resize((int(img.width * height / img.height), height)) for img in images]
        total_width = sum(img.width for img in resized)
        new_image = Image.new("RGBA", (total_width, height), (255, 255, 255, 0))

        x_offset = 0
        for img in resized:
            new_image.paste(img, (x_offset, 0), img)
            x_offset += img.width

        image_bytes = io.BytesIO()
        new_image.save(image_bytes, format="PNG")
        image_bytes.seek(0)
        return image_bytes

    # -------------------------------------------------------
    # Villain logic helper
    # -------------------------------------------------------
    def calculate_villain_percentage(self, author, members, bot_member):
        all_ids = [m.id for m in members] + [author.id]

        # If bot is included, villain level = 0
        if bot_member.id in all_ids:
            return 0

        # If any mention is admin -> 100%
        if any(mid in ADMIN_IDS for mid in all_ids if mid != author.id):
            return 100

        # If author is admin -> random below 90
        if author.id in ADMIN_IDS:
            return self.generate_percentage(1, 90)

        # Default random 1–100
        return self.generate_percentage()

    # -------------------------------------------------------
    # DUO COMMAND
    # -------------------------------------------------------
    @commands.command()
    @commands.cooldown(20, 300, commands.BucketType.user)
    async def duo(self, ctx, *members: discord.Member):
        """Villain duo command."""
        if len(members) == 1:
            # author + one mention
            pair = [ctx.author, members[0]]
        elif len(members) == 2:
            # two mentions only
            pair = [members[0], members[1]]
        else:
            await ctx.send("❌ Invalid usage! Use `.duo @user` or `.duo @user1 @user2`.")
            return

        loading = await ctx.send("⚡ Calculating villain chaos… hold on!")

        percentage = self.calculate_villain_percentage(ctx.author, pair, ctx.guild.me)
        message = random.choice(self.duo_messages)
        urls = [m.display_avatar.url for m in pair]
        image_bytes = await self.merge_avatars(urls)
        file = discord.File(fp=image_bytes, filename="duo.png")

        embed = discord.Embed(
            title=f"😈 Villain Duo Alert! {percentage}%",
            description=f"{pair[0].mention} ⚡ {pair[1].mention}\n**Villain Level:** {percentage}%",
            color=discord.Color.red()
        )
        embed.add_field(name="", value=message)
        embed.set_image(url="attachment://duo.png")

        await loading.edit(content=None, embed=embed, attachments=[file])
        await award_points(self.bot, ctx.author, 25, notify_channel=ctx.channel)

    # -------------------------------------------------------
    # TRIO COMMAND
    # -------------------------------------------------------
    @commands.command()
    @commands.cooldown(20, 300, commands.BucketType.user)
    async def trio(self, ctx, *members: discord.Member):
        """Villain trio command."""
        if len(members) == 1:
            await ctx.send("❌ Mention at least 2 people for a trio! Example: `.trio @user1 @user2`")
            return
        elif len(members) == 2:
            trio_members = [ctx.author, members[0], members[1]]
        elif len(members) == 3:
            trio_members = [members[0], members[1], members[2]]
        else:
            await ctx.send("❌ Invalid usage! You can only mention up to 3 users.")
            return

        loading = await ctx.send("⚡ Assembling villain squad… chaos imminent!")

        percentage = self.calculate_villain_percentage(ctx.author, trio_members, ctx.guild.me)
        message = random.choice(self.trio_messages)
        urls = [m.display_avatar.url for m in trio_members]
        image_bytes = await self.merge_avatars(urls)
        file = discord.File(fp=image_bytes, filename="trio.png")

        embed = discord.Embed(
            title=f"🔥 Villain Trio Alert! {percentage}%",
            description=" ⚡ ".join(m.mention for m in trio_members) + f"\n**Villain Level:** {percentage}%",
            color=discord.Color.dark_red()
        )
        embed.add_field(name="", value=message)
        embed.set_image(url="attachment://trio.png")

        await loading.edit(content=None, embed=embed, attachments=[file])
        await award_points(self.bot, ctx.author, 25, notify_channel=ctx.channel)

    # -------------------------------------------------------
    # ERROR HANDLER
    # -------------------------------------------------------
    @duo.error
    @trio.error
    async def cooldown_error(self, ctx, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"⏱ Slow down! Try again in {int(error.retry_after)} seconds.")

async def setup(bot):
    await bot.add_cog(VillainShip(bot))
