import discord
from discord.ext import commands
import random
from PIL import Image
import aiohttp
import io
import os
from helpers import (award_points)

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

    def generate_percentage(self):
        return random.randint(1, 100)

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

    @commands.command()
    @commands.cooldown(20, 300, commands.BucketType.user)
    async def duo(self, ctx, member: discord.Member = None):
        if member is None:
            member = ctx.guild.me  # Default to bot if no mention

        loading = await ctx.send("⚡ Calculating villain chaos… hold on!")

        # Determine villain percentage
        if member.id == ctx.guild.me.id:
            percentage = 0  # Always 0% if duo is with the bot
        elif ctx.author.id in ADMIN_IDS or member.id in ADMIN_IDS:
            percentage = 100
        else:
            percentage = self.generate_percentage()

        message = random.choice(self.duo_messages)

        image_bytes = await self.merge_avatars([ctx.author.display_avatar.url, member.display_avatar.url])
        file = discord.File(fp=image_bytes, filename="duo.png")

        embed = discord.Embed(
            title=f"😈 Villain Duo Alert! {percentage}%",
            description=f"{ctx.author.mention} ⚡ {member.mention}\n**Villain Level:** {percentage}%",
            color=discord.Color.red()
        )
        embed.set_image(url="attachment://duo.png")
        embed.add_field(name="", value=message)

        await loading.edit(content=None, embed=embed, attachments=[file])
        await award_points(self.bot, ctx.author, 10, notify_channel=ctx.channel)
    @commands.command()
    @commands.cooldown(20, 300, commands.BucketType.user)
    async def trio(self, ctx, member1: discord.Member = None, member2: discord.Member = None):
        if member1 is None:
            member1 = ctx.guild.me
        if member2 is None:
            member2 = ctx.author

        loading = await ctx.send("⚡ Assembling villain squad… chaos imminent!")

        # Determine villain percentage
        if ctx.author.id in ADMIN_IDS or member1.id in ADMIN_IDS or member2.id in ADMIN_IDS:
            percentage = 100
        else:
            percentage = self.generate_percentage()

        message = random.choice(self.trio_messages)

        image_bytes = await self.merge_avatars([
            ctx.author.display_avatar.url,
            member1.display_avatar.url,
            member2.display_avatar.url
        ])
        file = discord.File(fp=image_bytes, filename="trio.png")

        embed = discord.Embed(
            title=f"😈 Villain Trio Alert! {percentage}%",
            description=f"{ctx.author.mention} ⚡ {member1.mention} ⚡ {member2.mention}\n**Villain Level:** {percentage}%",
            color=discord.Color.dark_red()
        )
        embed.set_image(url="attachment://trio.png")
        embed.add_field(name="", value=message)

        await loading.edit(content=None, embed=embed, attachments=[file])
        await award_points(self.bot, ctx.author, 10, notify_channel=ctx.channel)
    @duo.error
    @trio.error
    async def cooldown_error(self, ctx, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"⏱ Slow down! Try again in {int(error.retry_after)} seconds.")

async def setup(bot):
    await bot.add_cog(VillainShip(bot))
