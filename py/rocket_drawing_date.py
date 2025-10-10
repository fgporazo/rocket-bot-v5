import os
import random
import asyncio
import discord
from discord.ext import commands
from dotenv import load_dotenv
from PIL import Image
import aiohttp
import io
from helpers import award_points,check_main_guild

load_dotenv()
SUBMISSION_CHANNEL_ID = int(os.getenv("DRAWING_SUBMISSION_CHANNEL", 0))


# Helper to fetch last submitted image from fixed channel
async def get_last_image(member: discord.Member, channel: discord.TextChannel):
    async for msg in channel.history(limit=200):  # scan last 200 messages
        if msg.author.id == member.id and msg.attachments:
            for att in msg.attachments:
                if att.content_type and att.content_type.startswith("image/"):
                    return att.url
    return None


# Helper to download image from URL
async def download_image(url: str):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                return None
            data = await resp.read()
            return Image.open(io.BytesIO(data)).convert("RGBA")


# Combine two images side by side
async def merge_images_side_by_side(img1_url: str, img2_url: str):
    img1 = await download_image(img1_url)
    img2 = await download_image(img2_url)
    if not img1 or not img2:
        return None

    # Resize both to same height
    height = 400
    w1 = int(img1.width * (height / img1.height))
    w2 = int(img2.width * (height / img2.height))
    img1 = img1.resize((w1, height))
    img2 = img2.resize((w2, height))

    # Create canvas
    combined = Image.new("RGBA", (w1 + w2, height), (255, 255, 255, 255))
    combined.paste(img1, (0, 0))
    combined.paste(img2, (w1, 0))

    output = io.BytesIO()
    combined.save(output, format="PNG")
    output.seek(0)
    return discord.File(output, filename="drawing_date.png")


class DoneButton(discord.ui.View):
    def __init__(self, drawer_name: str):
        super().__init__(timeout=None)
        self.drawer_name = drawer_name
        self.done = asyncio.Event()

    @discord.ui.button(label="I'm done 💖", style=discord.ButtonStyle.success)
    async def done_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(f"✅ {self.drawer_name} finished their drawing!", ephemeral=True)
        self.done.set()


class DateView:
    def __init__(self, ctx, author: discord.Member, target: discord.Member):
        self.ctx = ctx
        self.author = author
        self.target = target
        self.turn_images = {}  # {drawer_name: image_url}
        self.whiteboard_folder = "assets/drawing/whiteboard"

    async def show_whiteboard(self, drawer: discord.Member, target: discord.Member):
        files = [f for f in os.listdir(self.whiteboard_folder)
                 if f.lower().endswith((".png", ".jpg", ".jpeg", ".gif"))]
        if not files:
            await self.ctx.send("❌ No whiteboard assets found!")
            return
        chosen = random.choice(files)
        file_path = os.path.join(self.whiteboard_folder, chosen)

        embed = discord.Embed(
            title=f"🎨 {drawer.display_name} is drawing {target.display_name}...",
            description="Click the button below when you finish your drawing!",
            color=discord.Color.purple()
        )
        embed.set_image(url=f"attachment://{chosen}")
        file = discord.File(file_path, filename=chosen)

        view = DoneButton(drawer.display_name)
        msg = await self.ctx.send(embed=embed, file=file, view=view)
        await view.done.wait()
        await msg.edit(view=None)

    async def show_result_image(self, drawer: discord.Member, use_photo_from: discord.Member):
        sub_channel = self.ctx.guild.get_channel(SUBMISSION_CHANNEL_ID)
        if not sub_channel:
            await self.ctx.send("❌ Submission channel not found!")
            return

        image_url = await get_last_image(use_photo_from, sub_channel)
        if not image_url:
            await self.ctx.send(
                f"❌ {use_photo_from.mention} has not submitted an image in {sub_channel.mention} yet!"
            )
            return

        embed = discord.Embed(
            title=f"🖼️ {drawer.display_name}'s drawing result of {use_photo_from.display_name}!",
            color=discord.Color.green()
        )
        embed.set_image(url=image_url)
        await self.ctx.send(embed=embed)

        self.turn_images[drawer.display_name] = image_url

    async def show_final_result(self):
        if len(self.turn_images) < 2:
            await self.ctx.send("❌ Not enough drawings to create final result!")
            return

        author_url = self.turn_images.get(self.author.display_name)
        target_url = self.turn_images.get(self.target.display_name)

        merged_file = await merge_images_side_by_side(author_url, target_url)
        if not merged_file:
            await self.ctx.send("❌ Could not merge images.")
            return

        embed = discord.Embed(
            title="💘 Team Rocket Special Drawing Date Result!",
            description=f"{self.author.mention} ❤️ {self.target.mention}\n"
                        f"✨ A masterpiece of love, drawn together on the Rocket canvas!",
            color=discord.Color.gold()
        )
        embed.set_footer(text="🎨 Jessie & James proudly present your art date 💕")

        await self.ctx.send(embed=embed, file=merged_file)
        await award_points(self.ctx.bot, self.author, 15, notify_channel=self.ctx.channel)
        await award_points(self.ctx.bot, self.target, 15, notify_channel=self.ctx.channel)

class RocketDrawingDate(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="dd")
    async def dd(self, ctx, member: discord.Member = None):

        if not await check_main_guild(ctx):
            return  # stop execution if not in main server

        if not member:
            help_text = f"`.dd @username` - mention who you want to drawing date."
            await ctx.send(f"📖 **Team Rocket Drawing Date Commands Guide**\n{help_text}")
        if member.id == ctx.author.id:
            return await ctx.send("❌ You cannot date yourself!")

        sub_channel = ctx.guild.get_channel(SUBMISSION_CHANNEL_ID)
        if not sub_channel:
            return await ctx.send("❌ Submission channel not found!")

        # Check both have submitted images
        author_image = await get_last_image(ctx.author, sub_channel)
        target_image = await get_last_image(member, sub_channel)

        if not author_image or not target_image:
            missing = []
            if not author_image:
                missing.append(ctx.author.mention)
            if not target_image:
                missing.append(member.mention)
            return await ctx.send(
                f"❌ {' and '.join(missing)} must submit portrait in {sub_channel.mention} before starting a date!"
            )

        game = DateView(ctx, ctx.author, member)

        # 1: Author phase
        await game.show_whiteboard(ctx.author, member)
        await game.show_result_image(ctx.author, use_photo_from=member)

        # 2: Target phase
        await game.show_whiteboard(member, ctx.author)
        await game.show_result_image(member, use_photo_from=ctx.author)

        # 3: Final combined result
        await game.show_final_result()


async def setup(bot):
    await bot.add_cog(RocketDrawingDate(bot))
