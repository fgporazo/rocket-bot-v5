import os
import discord
from discord import app_commands, Embed, Color, Button
from discord.ext import commands
from discord.ui import View
import asyncio
import random

# ---------------- Admin IDs from ENV ----------------
ADMIN_IDS = set()
admin_ids_str = os.getenv("ADMIN_IDS", "")
if admin_ids_str:
    ADMIN_IDS = set(int(x.strip()) for x in admin_ids_str.split(",") if x.strip().isdigit())

def is_admin(interaction: discord.Interaction) -> bool:
    return interaction.user.id in ADMIN_IDS

# ---------------- GIF Choices ----------------
GIT_CHOICES = [
    "https://media.tenor.com/JzGtcFnBEIMAAAAj/glitter-pikachu.gif",
    "https://i.pinimg.com/originals/50/30/a2/5030a2f440e5889cf58ea0ec27ad780a.gif",
    "https://www.picgifs.com/graphics/p/pokemon/graphics-pokemon-212030.gif",
    "https://i.pinimg.com/originals/0a/69/7a/0a697ac27c3b75e674a53cd98520b485.gif",
    "https://64.media.tumblr.com/4e39d8c5c762ca8beaef4c0a06529c42/tumblr_p4jja5ah4e1udszxdo1_400.gif",
]

# ---------------- Default Ticker ----------------
DEFAULT_TICKER = "💥 🚀 Team Rocket blasting off again! | ✨ Stay tuned for Rocket news!"

# ---------------- Announcement Channel ID ----------------
channel_id_str = os.getenv("ANNOUNCEMENT_CHANNEL_ID", "")
if channel_id_str.isdigit():
    ANNOUNCEMENT_CHANNEL_ID = int(channel_id_str)
else:
    ANNOUNCEMENT_CHANNEL_ID = 0


class RocketSlashNews(commands.Cog):
    MAX_ACTIVE_SCROLLS = 2  # limit simultaneous tickers

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active_users_per_message = {}  # track reactions per announcement
        self.active_scrolls = []

    # ---------------- Rocket News Command ----------------
    @app_commands.command(
        name="rocket-news",
        description="Simulate a Team Rocket TV news broadcast"
    )
    @app_commands.describe(
        headline="Main headline for the news",
        details="Detailed news description",
        ticker="Scrolling ticker text (separate by | ). Optional."
    )
    async def rocket_news(
        self,
        interaction: discord.Interaction,
        headline: str,
        details: str,
        ticker: str = None
    ):
        if not is_admin(interaction):
            await interaction.response.send_message(
                "🚫 Only admins can use this command.", ephemeral=True
            )
            return

        await interaction.response.defer()

        full_ticker = DEFAULT_TICKER if not ticker else "   ".join([t.strip() for t in ticker.split("|")])
        embed = Embed(
            title="🅰 🇳 🇳 🅾 🇺 🇳 🇨 🇪 🇲 🇪 🇳 🇹",
            description=f"\n**{headline.upper()}**\n\n{details}\n\n📢 {full_ticker}",
            color=Color.red()
        )

        class BroadcastButtons(View):
            @discord.ui.button(label="🔵 ON", style=discord.ButtonStyle.success)
            async def on_button(self, interaction: discord.Interaction, button: Button):
                button.disabled = True
                await interaction.message.edit(view=self)
                await interaction.response.send_message("You clicked ON! ⚡", ephemeral=True)

            @discord.ui.button(label="⚫ OFF", style=discord.ButtonStyle.danger)
            async def off_button(self, interaction: discord.Interaction, button: Button):
                button.disabled = True
                await interaction.message.edit(view=self)
                await interaction.response.send_message("You clicked OFF! ⚡", ephemeral=True)

            @discord.ui.button(label="🟡 Channel R", style=discord.ButtonStyle.secondary)
            async def channel_button(self, interaction: discord.Interaction, button: Button):
                button.disabled = True
                await interaction.message.edit(view=self)
                await interaction.response.send_message("You clicked Channel R! ⚡", ephemeral=True)

        view = BroadcastButtons()

        try:
            embed_msg = await interaction.followup.send(embed=embed, view=view, wait=True)
        except discord.errors.InteractionResponded:
            return

        # ✅ Auto-add reactions
        for emoji in ["👀", "🫶", "🔥", "⭐", "🙌"]:
            try:
                await embed_msg.add_reaction(emoji)
            except discord.HTTPException:
                pass

        # ---------------- Scroll ticker ----------------
        async def scroll_ticker():
            if len(self.active_scrolls) >= self.MAX_ACTIVE_SCROLLS:
                return
            self.active_scrolls.append(embed_msg.id)
            text = full_ticker + "   "
            try:
                while True:
                    for i in range(len(text)):
                        scroll = text[i:] + text[:i]
                        embed.description = f"\n**{headline.upper()}**\n\n{details}\n\n📢 {scroll}"
                        try:
                            await embed_msg.edit(embed=embed)
                        except discord.NotFound:
                            return
                        await asyncio.sleep(0.8)
            finally:
                self.active_scrolls.remove(embed_msg.id)

        asyncio.create_task(scroll_ticker())

    # ---------------- Reaction Listener ----------------
    @commands.Cog.listener()
    async def on_reaction_add(self, reaction: discord.Reaction, user: discord.User):
        if user.bot:
            return
        if reaction.message.channel.id != ANNOUNCEMENT_CHANNEL_ID:
            return
        if reaction.message.author.id != self.bot.user.id:
            return
        if not reaction.message.embeds:
            return

        # ---------------- IGNORE reactions on popup messages ----------------
        if any(tracker.get("popup_msg") and tracker["popup_msg"].id == reaction.message.id
               for tracker in self.active_users_per_message.values()):
            return  # do nothing if reaction is on popup

        msg_id = reaction.message.id
        tracker = self.active_users_per_message.get(msg_id)

        if not tracker:
            # If no popup tracked yet, create tracker
            tracker = {"users": [], "popup_msg": None}
            self.active_users_per_message[msg_id] = tracker

        if user.id in tracker["users"]:
            return
        if len(tracker["users"]) >= 5:
            return

        tracker["users"].append(user.id)

        # ---------------- Prepare embed ----------------
        order_texts = [
            "first to react! 🚀",
            "second to react! Team Rocket salutes you!",
            "third to react and witness our glory!",
            "fourth to react! Chaos intensifies!",
            "fifth to react! You rock!"
        ]
        emojis = ["✨", "🌟", "💥", "🌟", "✨"]

        rocket_texts = []
        for idx, uid in enumerate(tracker["users"]):
            try:
                member = reaction.message.guild.get_member(uid) or await reaction.message.guild.fetch_member(uid)
                mention = member.mention
            except discord.NotFound:
                mention = f"<@{uid}>"
            rocket_texts.append(f"{emojis[idx]} {idx+1}. {mention} — {order_texts[idx]}")

        rocket_text = "\n".join(rocket_texts)
        chosen_gif = random.choice(GIT_CHOICES)

        embed = Embed(
            title="Your reaction Matters! ✨",
            description=rocket_text,
            color=Color.red()
        )
        embed.set_thumbnail(url=chosen_gif)

        # ---------------- Update or create popup ----------------
        if tracker["popup_msg"] is None:
            tracker["popup_msg"] = await reaction.message.channel.send(embed=embed)
        else:
            try:
                await tracker["popup_msg"].edit(embed=embed)
            except discord.NotFound:
                tracker["popup_msg"] = await reaction.message.channel.send(embed=embed)

        # Auto-clean old entries
        asyncio.create_task(self.cleanup_message(msg_id, delay=900))

    async def cleanup_message(self, msg_id, delay=900):
        await asyncio.sleep(delay)
        self.active_users_per_message.pop(msg_id, None)


# ---------------- Setup Cog ----------------
async def setup(bot: commands.Bot):
    await bot.add_cog(RocketSlashNews(bot))
