import discord
from discord.ext import commands
from discord import ui
import os
import re

SHOP_PRIVATE_CHANNEL_ID = int(os.getenv("SHOP_PRIVATE_CHANNEL_ID", 0))
SHOP_PUBLIC_CHANNEL_ID = int(os.getenv("SHOP_PUBLIC_CHANNEL_ID", 0))
LEADERBOARD_CHANNEL_ID = int(os.getenv("LEADERBOARD_CHANNEL_ID", 0))

GRAY_COLOR = "#2F3136"

class RocketShop(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.shop_items = []

    async def cog_load(self):
        print("[DEBUG] Cog loaded, loading shop items...")
        await self.load_shop_items()

    async def load_shop_items(self):
        channel = self.bot.get_channel(SHOP_PRIVATE_CHANNEL_ID)
        if not channel:
            print("[DEBUG] SHOP_PRIVATE_CHANNEL_ID not found")
            return
        try:
            msg = [m async for m in channel.history(limit=1, oldest_first=False)][0]
        except IndexError:
            print("[DEBUG] No messages found in SHOP_PRIVATE_CHANNEL_ID")
            return
        self.shop_items = self.parse_shop_message(msg.content)
        print(f"[DEBUG] Loaded {len(self.shop_items)} shop items")

    def parse_shop_message(self, message_content: str):
        items = []
        for line in message_content.splitlines():
            parts = [p.strip() for p in line.split("|")]
            if len(parts) == 6:
                name, description, power, price, emoji_react, color = parts
                try:
                    gems = int(re.sub(r"\D", "", price))
                except ValueError:
                    continue
                items.append({
                    "name": name,
                    "description": description,
                    "power": power,
                    "gems": gems,
                    "emoji_react": emoji_react,
                    "color": color or GRAY_COLOR
                })
        return items

    async def get_leaderboard_points(self, user_id: int):
        channel = self.bot.get_channel(LEADERBOARD_CHANNEL_ID)
        if not channel:
            return 0
        try:
            msg = [m async for m in channel.history(limit=1, oldest_first=False)][0]
        except IndexError:
            return 0
        lines = msg.content.splitlines()
        for line in lines:
            parts = [p.strip() for p in line.split("-")]
            if len(parts) == 3:
                _, uid, gems = parts
                if str(user_id) == uid:
                    try:
                        return int(re.sub(r"\D", "", gems))
                    except ValueError:
                        return 0
        return 0

    async def update_leaderboard_points(self, user_id: int, new_points: int):
        channel = self.bot.get_channel(LEADERBOARD_CHANNEL_ID)
        if not channel:
            return
        try:
            msg = [m async for m in channel.history(limit=1, oldest_first=False)][0]
        except IndexError:
            await channel.send(f"{self.bot.get_user(user_id).display_name} - {user_id} - {new_points}")
            return

        lines = msg.content.splitlines()
        new_lines = []
        user_found = False
        for line in lines:
            parts = [p.strip() for p in line.split("-")]
            if len(parts) == 3:
                name, uid, gems = parts
                if str(user_id) == uid:
                    new_lines.append(f"{name} - {uid} - {new_points}")
                    user_found = True
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)
        if not user_found:
            new_lines.append(f"{self.bot.get_user(user_id).display_name} - {user_id} - {new_points}")

        await msg.edit(content="\n".join(new_lines))

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.channel_id != SHOP_PUBLIC_CHANNEL_ID or payload.user_id == self.bot.user.id:
            return
        guild = self.bot.get_guild(payload.guild_id)
        member = guild.get_member(payload.user_id)
        if not member:
            return
        emoji = str(payload.emoji)
        await self.load_shop_items()
        for item in self.shop_items:
            if emoji == item["emoji_react"]:
                role = discord.utils.get(guild.roles, name=item["name"])
                user_points = await self.get_leaderboard_points(member.id)
                if role and role in member.roles:
                    try:
                        await member.send(f"⚠️ You already have **{item['name']}**!")
                    except:
                        pass
                    return
                try:
                    # Embed with clean bold labels
                    embed = discord.Embed(
                        title=f"{item['name']}",
                        description=(
                            f"**Description:** {item['description']}\n"
                            f"**Power:** {item['power']}\n"
                            f"**Price:** {item['gems']:,} gems 💎"
                        ),
                        color=discord.Color(int(item['color'].replace("#", "0x"), 16))
                    )
                    embed.set_footer(text=f"💎 You currently have {user_points} gems")
                    view = ConfirmPurchaseView(member, item, self)
                    await member.send(embed=embed, view=view)
                except Exception as e:
                    print(f"[ERROR] Sending embed: {e}")
                break


class ConfirmPurchaseView(ui.View):
    def __init__(self, member, item, cog):
        super().__init__(timeout=60)
        self.member = member
        self.item = item
        self.cog = cog

    @ui.button(label="Buy", style=discord.ButtonStyle.green)
    async def buy(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.member.id:
            await interaction.response.send_message("This is not for you!", ephemeral=True)
            return
        user_points = await self.cog.get_leaderboard_points(self.member.id)
        if user_points < self.item["gems"]:
            await interaction.response.send_message(
                f"❌ You don’t have enough gems for **{self.item['name']}**.\n"
                f"🗓️ Join **events** or play in **Rocketverse** to earn **gems**.\n"
                f"💎 You currently have **{user_points}** gems.", ephemeral=True
            )
            self.stop()
            return

        await self.cog.update_leaderboard_points(self.member.id, user_points - self.item["gems"])
        guild = self.member.guild
        role = discord.utils.get(guild.roles, name=self.item["name"])
        if not role:
            role = await guild.create_role(
                name=self.item["name"],
                color=discord.Color(int(self.item["color"].replace("#", "0x"), 16))
            )
        await self.member.add_roles(role)
        await interaction.response.send_message(
            f"✅ You bought **{self.item['name']}**!\n💎 Remaining gems: {user_points - self.item['gems']}", ephemeral=True
        )
        self.stop()

    @ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.member.id:
            await interaction.response.send_message("This is not for you!", ephemeral=True)
            return
        await interaction.response.send_message(f"❌ Purchase canceled.", ephemeral=True)
        self.stop()


async def setup(bot):
    await bot.add_cog(RocketShop(bot))
