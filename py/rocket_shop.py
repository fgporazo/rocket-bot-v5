import discord
from discord.ext import commands
from discord import ui
import os
import re
import time

SHOP_PRIVATE_CHANNEL_ID = int(os.getenv("SHOP_PRIVATE_CHANNEL_ID", 0))
SHOP_PUBLIC_CHANNEL_ID = int(os.getenv("SHOP_PUBLIC_CHANNEL_ID", 0))
LEADERBOARD_CHANNEL_ID = int(os.getenv("LEADERBOARD_CHANNEL_ID", 0))
INVENTORY_CHANNEL_ID = int(os.getenv("INVENTORY_CHANNEL_ID", 0))

GRAY_COLOR = "#2F3136"

SPAM_REACTIONS = 3
COOLDOWN_SECONDS = 300  # 5 minutes
CONFIRMATION_TIMEOUT = 15  # seconds


class RocketShop(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.shop_items = []
        self.cached_inventory_msg = None
        self.cached_leaderboard_msg = None
        self.inventory_data = {}  # user_id -> {"name": str, "items": {(emoji,item_name): count}}
        self.leaderboard_data = {}
        self.user_reaction_counts = {}  # user_id -> [count, first_reaction_time]
        self.user_cooldowns = {}  # user_id -> cooldown_end_timestamp

    async def cog_load(self):
        await self.load_shop_items()
        await self.load_inventory()
        await self.load_leaderboard()

    # -------------------------
    # Load messages
    # -------------------------
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

    async def load_inventory(self):
        channel = self.bot.get_channel(INVENTORY_CHANNEL_ID)
        if not channel:
            return
        try:
            msg = [m async for m in channel.history(limit=1, oldest_first=False)][0]
        except IndexError:
            self.cached_inventory_msg = None
            self.inventory_data = {}
            return
        self.cached_inventory_msg = msg
        self.inventory_data = self.parse_inventory(msg.content)

    async def load_leaderboard(self):
        channel = self.bot.get_channel(LEADERBOARD_CHANNEL_ID)
        if not channel:
            return
        try:
            msg = [m async for m in channel.history(limit=1, oldest_first=False)][0]
        except IndexError:
            self.cached_leaderboard_msg = None
            self.leaderboard_data = {}
            return
        self.cached_leaderboard_msg = msg
        self.leaderboard_data = self.parse_leaderboard(msg.content)

    # -------------------------
    # Parsers
    # -------------------------
    def parse_inventory(self, text):
        data = {}
        for line in text.splitlines():
            if "|" not in line:
                continue
            name_id_part, *items_part = line.split("|")
            if "-" not in name_id_part:
                continue
            name, uid = [x.strip() for x in name_id_part.split("-", 1)]
            inv = {}
            for itemtxt in items_part:
                match = re.match(r"(\S+)\s+(\d+)x\s+(.+)", itemtxt.strip())
                if match:
                    emoji, count, item_name = match.groups()
                    inv[(emoji, item_name.strip())] = int(count)
            data[uid] = {"name": name, "items": inv}
        return data

    def parse_leaderboard(self, text):
        data = {}
        for line in text.splitlines():
            if "-" not in line:
                continue
            parts = [x.strip() for x in line.split("-")]
            if len(parts) < 3:
                continue
            uid = parts[1].strip()
            try:
                gems = int(re.sub(r"\D", "", parts[2]))
            except:
                gems = 0
            data[uid] = gems
        return data

    def parse_shop_message(self, text):
        items = []
        for line in text.splitlines():
            parts = [p.strip() for p in line.split("|")]
            if len(parts) != 6:
                continue
            emoji, name, alias, description, reward, price = parts
            try:
                gems = int(re.sub(r"\D", "", price))
            except:
                continue
            items.append({
                "emoji": emoji,
                "name": name,
                "alias": alias.strip("()"),
                "description": description,
                "reward": reward,
                "gems": gems
            })
        return items

    # -------------------------
    # Helper functions
    # -------------------------
    async def get_user_gems(self, user_id: int):
        return self.leaderboard_data.get(str(user_id), 0)

    async def update_user_gems(self, user_id: int, new_gems: int):
        self.leaderboard_data[str(user_id)] = new_gems
        if not self.cached_leaderboard_msg:
            return
        lines = self.cached_leaderboard_msg.content.splitlines()
        new_lines = []
        found = False
        for line in lines:
            parts = [x.strip() for x in line.split("-")]
            if len(parts) == 3 and parts[1] == str(user_id):
                new_lines.append(f"{parts[0]} - {parts[1]} - {new_gems}")
                found = True
            else:
                new_lines.append(line)
        if not found:
            new_lines.append(f"{self.bot.get_user(user_id).display_name} - {user_id} - {new_gems}")
        await self.cached_leaderboard_msg.edit(content="\n".join(new_lines))

    async def add_item_to_inventory(self, user_id: int, item_name: str, user_name: str, item_emoji: str):
        uid = str(user_id)
        user_data = self.inventory_data.get(uid, {"name": user_name, "items": {}})
        items = user_data["items"]
        key = (item_emoji, item_name)
        items[key] = items.get(key, 0) + 1
        self.inventory_data[uid] = {"name": user_name, "items": items}

        # Fetch channel
        channel = self.bot.get_channel(INVENTORY_CHANNEL_ID) or await self.bot.fetch_channel(INVENTORY_CHANNEL_ID)
        if not channel:
            print("[DEBUG] Inventory channel not found")
            return

        # Build content
        lines = []
        for u, data in self.inventory_data.items():
            name = data["name"]
            items = data["items"]
            item_str = " | ".join(f"{emoji} {count}x {iname}" for (emoji, iname), count in items.items())
            lines.append(f"{name} - {u} | {item_str}" if item_str else f"{name} - {u} |")
        content = "\n".join(lines)

        # Check last message in channel
        try:
            last_msg = [m async for m in channel.history(limit=1)][0]
        except IndexError:
            last_msg = None

        if last_msg:
            self.cached_inventory_msg = last_msg
            await last_msg.edit(content=content)
        else:
            self.cached_inventory_msg = await channel.send(content)

    # -------------------------
    # Reaction listener with spam/cooldown
    # -------------------------
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.channel_id != SHOP_PUBLIC_CHANNEL_ID or payload.user_id == self.bot.user.id:
            return

        user_id = payload.user_id
        now = time.time()

        # check cooldown
        cooldown_end = self.user_cooldowns.get(user_id, 0)
        if now < cooldown_end:
            remaining = int(cooldown_end - now)
            guild = self.bot.get_guild(payload.guild_id)
            member = guild.get_member(user_id) or await guild.fetch_member(user_id)
            if member:
                channel = self.bot.get_channel(payload.channel_id)
                await channel.send(f"{member.mention} ❌ You are on cooldown for {remaining} more seconds.",
                                   delete_after=10)
            return

        # track reaction counts
        count, first_time = self.user_reaction_counts.get(user_id, (0, now))
        if now - first_time > COOLDOWN_SECONDS:
            count = 0
            first_time = now
        count += 1
        self.user_reaction_counts[user_id] = [count, first_time]

        if count > SPAM_REACTIONS:
            self.user_cooldowns[user_id] = now + COOLDOWN_SECONDS
            self.user_reaction_counts[user_id] = [0, 0]
            guild = self.bot.get_guild(payload.guild_id)
            member = guild.get_member(user_id) or await guild.fetch_member(user_id)
            if member:
                channel = self.bot.get_channel(payload.channel_id)
                await channel.send(
                    f"{member.mention} ❌ You reached {SPAM_REACTIONS} purchases. Cooldown for {COOLDOWN_SECONDS // 60} minutes.",
                    delete_after=10)
            return

        guild = self.bot.get_guild(payload.guild_id)
        member = guild.get_member(user_id) or await guild.fetch_member(user_id)
        if not member:
            return

        await self.load_shop_items()
        await self.load_leaderboard()

        # find item by emoji
        for item in self.shop_items:
            if str(payload.emoji) == item["emoji"]:
                user_gems = await self.get_user_gems(user_id)
                embed = discord.Embed(
                    title=f"{item['name']}",
                    description=(
                        f"**Description:** {item['description']}\n"
                        f"**Potential Reward:** {item['reward']}\n"
                        f"**Price:** {item['gems']:,} gems"
                    ),
                    color=discord.Color(int(GRAY_COLOR.replace("#", "0x"), 16))
                )
                embed.set_footer(text=f"💎 You currently have {user_gems:,} gems")
                view = ConfirmPurchaseView(member, item, self, CONFIRMATION_TIMEOUT)

                channel = self.bot.get_channel(payload.channel_id)
                await channel.send(
                    content=f"{member.mention}, Are you sure you want to buy **{item['name']}**?",
                    embed=embed,
                    view=view
                )
                break


# -------------------------
# Purchase view in-channel
# -------------------------
class ConfirmPurchaseView(ui.View):
    def __init__(self, member, item, cog, timeout=15):
        super().__init__(timeout=timeout)
        self.member = member
        self.item = item
        self.cog = cog
        self.message = None

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.delete()
            except:
                pass
        self.stop()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.member.id:
            await interaction.response.send_message("This is not for you!", ephemeral=True)
            return False
        return True

    @ui.button(label="Buy", style=discord.ButtonStyle.green)
    async def buy(self, interaction: discord.Interaction, button: ui.Button):
        user_gems = await self.cog.get_user_gems(self.member.id)
        if user_gems < self.item["gems"]:
            self.disable_all_buttons()
            if interaction.message:
                await interaction.message.delete()
            await interaction.response.send_message(
                f"❌ Not enough gems for **{self.item['name']}**.\n💎 You have {user_gems:,} gems.",
                ephemeral=True
            )
            self.stop()
            return

        remain_gems = user_gems - self.item["gems"]
        await self.cog.update_user_gems(self.member.id, remain_gems)
        await self.cog.add_item_to_inventory(
            self.member.id, self.item["name"], self.member.display_name, self.item["emoji"]
        )
        await interaction.response.send_message(
            f"✅ You bought **{self.item['name']}**! Remaining gems: {remain_gems:,}", ephemeral=True
        )
        if interaction.message:
            await interaction.message.delete()
        self.stop()

    @ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message(f"❌ Purchase canceled.", ephemeral=True)
        if interaction.message:
            await interaction.message.delete()
        self.stop()

    def disable_all_buttons(self):
        for child in self.children:
            child.disabled = True


async def setup(bot):
    await bot.add_cog(RocketShop(bot))
