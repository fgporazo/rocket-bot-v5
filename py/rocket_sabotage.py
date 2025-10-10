import discord
from discord.ext import commands
import os
import re
from helpers import award_points,check_main_guild

INVENTORY_CHANNEL_ID = int(os.getenv("INVENTORY_CHANNEL_ID", 0))
LEADERBOARD_CHANNEL_ID = int(os.getenv("LEADERBOARD_CHANNEL_ID", 0))
SHOP_PUBLIC_CHANNEL_ID = int(os.getenv("SHOP_PUBLIC_CHANNEL_ID", 0))

POKEBAG_THUMBNAIL_URL = "https://i.postimg.cc/Y2YGLRZ8/0b656b4c-d7e8-4679-8dc2-af9419bb7f38-removalai-preview.png"

class RocketSabotage(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.shop_channel = None
        self.cached_inventory_msg = None
        self.cached_leaderboard_msg = None
        self.inventory_data = {}  # uid -> {"name": str, "items": {(emoji,item_name): count}}
        self.leaderboard_data = {}  # uid -> gems

    async def cog_load(self):
        self.shop_channel = self.bot.get_channel(SHOP_PUBLIC_CHANNEL_ID)
        await self.load_inventory()
        await self.load_leaderboard()

    # ------------------------
    # Loaders
    # ------------------------
    async def load_inventory(self):
        channel = self.bot.get_channel(INVENTORY_CHANNEL_ID)
        if not channel:
            print("[DEBUG] INVENTORY_CHANNEL_ID not found")
            return
        try:
            msg = [m async for m in channel.history(limit=1, oldest_first=False)][0]
            self.cached_inventory_msg = msg
            self.inventory_data = self.parse_inventory(msg.content)
        except IndexError:
            self.cached_inventory_msg = None
            self.inventory_data = {}

    async def load_leaderboard(self):
        channel = self.bot.get_channel(LEADERBOARD_CHANNEL_ID)
        if not channel:
            print("[DEBUG] LEADERBOARD_CHANNEL_ID not found")
            return
        try:
            msg = [m async for m in channel.history(limit=1, oldest_first=False)][0]
            self.cached_leaderboard_msg = msg
            self.leaderboard_data = self.parse_leaderboard(msg.content)
        except IndexError:
            self.cached_leaderboard_msg = None
            self.leaderboard_data = {}

    # ------------------------
    # Parsers
    # ------------------------
    def parse_inventory(self, text):
        data = {}
        for line in text.splitlines():
            if "|" not in line:
                continue
            name_id_part, *items_part = line.split("|")
            if "-" not in name_id_part:
                continue
            name, uid = [x.strip() for x in name_id_part.split("-", 1)]
            items = {}
            for itemtxt in items_part:
                match = re.match(r"(\S+)\s+(\d+)x\s+(.+)", itemtxt.strip())
                if match:
                    emoji, count, item_name = match.groups()
                    item_name_clean = item_name.strip().replace("’", "'")
                    items[(emoji, item_name_clean)] = int(count)
            data[uid] = {"name": name, "items": items}
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

    # ------------------------
    # Inventory update / deduct
    # ------------------------
    async def update_inventory_message(self):
        lines = []
        for uid, data in self.inventory_data.items():
            item_strs = [f"{emoji} {count}x {iname}" for (emoji, iname), count in data["items"].items()]
            line = f"{data['name']} - {uid} | " + " | ".join(item_strs) if item_strs else f"{data['name']} - {uid} |"
            lines.append(line)
        content = "\n".join(lines) if lines else "No inventory yet."

        channel = self.bot.get_channel(INVENTORY_CHANNEL_ID)
        if not channel:
            print("[DEBUG] INVENTORY_CHANNEL_ID not found")
            return

        if not self.cached_inventory_msg:
            self.cached_inventory_msg = await channel.send(content)
        else:
            await self.cached_inventory_msg.edit(content=content)

    async def deduct_item(self, user_id: int, emoji: str) -> bool:
        """Deduct one item from inventory by emoji. Return True if deducted, False if not enough."""
        uid = str(user_id)
        user_data = self.inventory_data.get(uid, {"name": str(user_id), "items": {}})
        items = user_data["items"]

        key_found = None
        for (e, n), count in items.items():
            if e == emoji and count > 0:
                key_found = (e, n)
                break

        if not key_found:
            return False

        items[key_found] -= 1
        if items[key_found] <= 0:
            del items[key_found]

        await self.update_inventory_message()
        return True

    async def check_and_deduct(self, ctx, emoji, item_name):
        """Check if user has an item by emoji, deduct one, else show shop link."""
        # Reload inventory to get fresh data
        await self.load_inventory()

        uid = str(ctx.author.id)
        items = self.inventory_data.get(uid, {}).get("items", {})

        key_found = None
        for (e, n), count in items.items():
            if e == emoji and n.strip().lower() == item_name.strip().lower() and count > 0:
                key_found = (e, n)
                break

        shop_channel = self.bot.get_channel(SHOP_PUBLIC_CHANNEL_ID)
        if not key_found:
            msg = f"❌ You don’t have **{item_name}**!"
            if shop_channel:
                msg += f" 🛒 Buy it from the shop: {shop_channel.mention}"
            await ctx.send(msg)
            return False

        # Deduct the item
        items[key_found] -= 1
        if items[key_found] <= 0:
            del items[key_found]

        await self.update_inventory_message()
        return True

    # ------------------------
    # Pokebag command
    # ------------------------
    @commands.command(aliases=["pb"],help="Show your Pokebag inventory and gems, or check another member's Pokebag (Shiled Viewing is private).")
    async def pokebag(self, ctx: commands.Context, member: discord.Member = None):

        if not await check_main_guild(ctx):
            return  # stop execution if not in main server

        await self.load_inventory()
        await self.load_leaderboard()
        target = member or ctx.author
        uid = str(target.id)
        user_data = self.inventory_data.get(uid, {"name": target.display_name, "items": {}})
        items = user_data["items"]
        visible_items = [f"{e} {c}x {n}" for (e,n),c in items.items() if n.lower() != "wobbuffet shield"]
        inv_text = "\n".join(visible_items) if visible_items else "\nNo visible items."
        user_gems = self.leaderboard_data.get(uid, 0)
        embed = discord.Embed(
            title=f"{user_data['name']}'s Pokebag",
            description=f"**📦 Items:**\n{inv_text}\n\n**💎 {user_gems:,}**",
            color=discord.Color.green()
        )
        embed.set_thumbnail(url=POKEBAG_THUMBNAIL_URL)
        shop_channel = self.bot.get_channel(SHOP_PUBLIC_CHANNEL_ID)


        if shop_channel:
            embed.add_field(name="\n", value=f"🛒 Visit {shop_channel.mention} to buy items", inline=False)
        embed.add_field(name="\n", value=f"📖 Type `.pi` to show Poke Item (Sabotage Game) Commands Guide\n📖 Type `.pokebag` to show Poke Bag", inline=False)
        await ctx.send(embed=embed)

        if target == ctx.author:
            protection_count = sum(
                count for (emoji, name), count in items.items() if name.lower() == "wobbuffet shield"
            )
            view = ShieldView(protection_count, owner_id=ctx.author.id, bot=self.bot)
            await ctx.send("", view=view)

    # ------------------------
    # .pi command group
    # ------------------------
    @commands.group(name="pi", invoke_without_command=True)
    async def pokeitem(self, ctx):
        if not await check_main_guild(ctx):
            return  # stop execution if not in main server

        commands_list = [
            f"`.pi {m.name}` - {m.help or 'No description'}"
            for m in self.pokeitem.commands
        ]
        commands_list.sort()
        help_text = "\n".join(commands_list)
        await ctx.send(f"📖 **Team Rocket - Poke Item (Sabotage Game) Commands Guide**\n{help_text}")
        await ctx.send(f"🛒 Visit <#{SHOP_PUBLIC_CHANNEL_ID}> to buy items.")

    @pokeitem.command(name="binocular",aliases=["bino", "james"],help="Use on a player to view their Pokebag items and Wobbuffet shields.")
    async def pi_binocular(self, ctx, member: discord.Member = None):

        if not await check_main_guild(ctx):
            return  # stop execution if not in main server

        if member is None:
            await ctx.send("❌ You need to mention a player to use the binocular.", ephemeral=True)
            return

        # Deduct binocular item from user
        if not await self.check_and_deduct(ctx, "🔭", "James's Binocular"):
            return

        # Show target's inventory publicly
        await ctx.invoke(self.pokebag, member=member)

        # Get target's Wobbuffet Shield count
        uid = str(member.id)
        user_items = self.inventory_data.get(uid, {}).get("items", {})
        shield_count = sum(count for (e, n), count in user_items.items() if n.lower() == "wobbuffet shield")

        # Add ShieldView so the user can click to check protection
        view = ShieldView(protection_count=shield_count, owner_id=ctx.author.id, bot=self.bot)
        await ctx.send(
            f"👀 {ctx.author.mention}, you are using your **James's Binocular** now! It will be deducted from your inventory."
            f"\n👇 Click below to see if {member.display_name}'s Pokebag has a Wobbuffet shield.",
            view=view
        )

    @pokeitem.command(name="potion", aliases=["love", "love_potion","jessie"],help="Use to request a Team Rocket-assisted date setup.")
    async def pi_potion(self, ctx, member: discord.Member = None):

        if not await check_main_guild(ctx):
            return  # stop execution if not in main server

        if not await self.check_and_deduct(ctx, "💖", "Jessie's Love Potion"):
            return
        team_rocket_role = discord.utils.get(ctx.guild.roles, name="TEAM ROCKET")
        mention = team_rocket_role.mention if team_rocket_role else "Team Rocket admins"
        await ctx.send(
            f"💖 {ctx.author.mention} used **Jessie's Love Potion**!\n"
            f"📢 {mention}, assemble and set up a date immediately!\n"
            f"⏳ If no one assists within 5 minutes, {mention} must give **double the potion price gems** to {ctx.author.mention}."
        )

    @pokeitem.command(name="vacuum",aliases=["vac", "meowth"], help="Use to steal 20% of another player's gems (fails if they have Wobbuffet Shield).")
    async def pi_vacuum(self, ctx, member: discord.Member = None):

        if not await check_main_guild(ctx):
            return  # stop execution if not in main server

        if member is None:
            await ctx.send("❌ You need to mention a player to use the vacuum.", ephemeral=True)
            return

        # Check if user has a vacuum
        if not await self.check_and_deduct(ctx, "🧹", "Meowth's Rare Gem Vacuum"):
            return

        uid_target = str(member.id)
        uid_actor = str(ctx.author.id)

        # Reload leaderboard to get accurate gem counts
        await self.load_leaderboard()
        target_gems_before = self.leaderboard_data.get(uid_target, 0)
        actor_gems_before = self.leaderboard_data.get(uid_actor, 0)

        # Check if target has Wobbuffet Shield
        target_items = self.inventory_data.get(uid_target, {}).get("items", {})
        shield_count = sum(count for (e, n), count in target_items.items() if n.lower() == "wobbuffet shield")
        if shield_count > 0:
            await ctx.send(f"🛡️ {member.display_name} has a **Wobbuffet Shield**! Your vacuum failed.", ephemeral=True)
            return

        # Calculate stolen gems (20% of target)
        stolen_gems = max(1, target_gems_before * 20 // 100)
        if stolen_gems <= 0:
            await ctx.send(f"💨 {member.display_name} has no gems to steal!", ephemeral=True)
            return

        # Use award_points to update both users
        await award_points(self.bot, ctx.author, stolen_gems, notify_channel=ctx.channel)
        await award_points(self.bot, member, -stolen_gems, notify_channel=ctx.channel)

        # Reload leaderboard to reflect updated totals
        await self.load_leaderboard()
        actor_gems_after = self.leaderboard_data.get(uid_actor, 0)
        target_gems_after = self.leaderboard_data.get(uid_target, 0)

        # Build embed
        embed = discord.Embed(
            title="🧹 Team Rocket Vacuum Heist!",
            description=f"{ctx.author.mention} successfully vacuumed **{stolen_gems:,} gems** from {member.mention}!",
            color=discord.Color.purple()
        )
        embed.add_field(
            name="💎 Previous Gems",
            value=f"{ctx.author.display_name}: {actor_gems_before:,}\n"
                  f"{member.display_name}: {target_gems_before:,}",
            inline=True
        )
        embed.add_field(
            name="💎 Gems After Vacuum",
            value=f"{ctx.author.display_name}: {actor_gems_after:,}\n"
                  f"{member.display_name}: {target_gems_after:,}",
            inline=True
        )
        embed.add_field(
            name="🎯 Gems Stolen",
            value=f"**{stolen_gems:,}**",
            inline=False
        )
        embed.set_footer(text="Team Rocket always aims for maximum gems! 🚀")
        embed.set_thumbnail(url="https://i.postimg.cc/Y2YGLRZ8/0b656b4c-d7e8-4679-8dc2-af9419bb7f38-removalai-preview.png")

        await ctx.send(embed=embed)

    # -------------------- GEMS --------------------
    @pokeitem.command(
        name="gems",
        aliases=["gem", "points"],
        help="Check your Rocketverse gems! 💎"
    )
    @commands.cooldown(rate=20, per=300, type=commands.BucketType.user)
    async def pi_gems(self, ctx: commands.Context):



        rocket_shop_cog = self.bot.get_cog("RocketShop")
        if not rocket_shop_cog:
            return await safe_send(ctx, "⚠️ RocketShop cog is not loaded.")

        channel = self.bot.get_channel(LEADERBOARD_CHANNEL_ID)
        if not channel:
            return await safe_send(ctx, "⚠️ Leaderboard channel not found!")

        try:
            msg = [m async for m in channel.history(limit=1, oldest_first=False)][0]
        except IndexError:
            return await safe_send(ctx, "⚠️ No leaderboard message found!")

        user_id_str = str(ctx.author.id)
        gems = 0

        for line in msg.content.splitlines():
            parts = [p.strip() for p in line.split("-")]
            if len(parts) == 3:
                _, uid, gems_str = parts
                if uid == user_id_str:
                    try:
                        gems = int(re.sub(r"\D", "", gems_str))
                    except ValueError:
                        gems = 0
                    break

        await ctx.send(f"💎 {ctx.author.mention}, you currently have **{gems:,} gems**!")  # <-- commas here
# ------------------------
# Shield Button View
# ------------------------
class ShieldView(discord.ui.View):
    def __init__(self, protection_count: int, owner_id: int, bot: commands.Bot):
        super().__init__(timeout=60)
        self.protection_count = protection_count
        self.owner_id = owner_id
        self.bot = bot
        self.shop_channel = self.bot.get_channel(SHOP_PUBLIC_CHANNEL_ID)

    @discord.ui.button(label="🛡️ View Protection", style=discord.ButtonStyle.blurple)
    async def show_protection(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "❌ Only the player who used `.pi binocular` or `.pokebag` command can view protection check.", ephemeral=True
            )
            return

        if self.protection_count > 0:
            msg = f"🛡️ Your Pokebag is protected **{self.protection_count}x** from Rare Gem Vacuum."
        else:
            if self.shop_channel:
                msg = f"⚠️ Your Pokebag is unprotected! Buy **Wobbuffet** in the shop: {self.shop_channel.mention}"
            else:
                msg = "⚠️ Your Pokebag is unprotected! Buy **Wobbuffet** in the shop."
        await interaction.response.send_message(msg, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(RocketSabotage(bot))
