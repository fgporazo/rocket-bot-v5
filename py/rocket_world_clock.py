from discord.ext import commands, tasks
from discord import app_commands, Interaction, Embed
from datetime import datetime
import pytz

class WorldClock(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.clock_message_id = None  # Message ID to edit
        self.channel_id = None        # Channel ID where the embed is posted
        self.timezones = {
            "Asia": [
                ("🇨🇳", "China", "Asia/Shanghai"),
                ("🇮🇳", "India", "Asia/Kolkata"),
                ("🇮🇩", "Indonesia", "Asia/Jakarta"),
                ("🇯🇵", "Japan", "Asia/Tokyo"),
                ("🇲🇾", "Malaysia", "Asia/Kuala_Lumpur"),
                ("🇵🇭", "Philippines", "Asia/Manila"),
                ("🇰🇷", "South Korea", "Asia/Seoul"),
                ("🇸🇬", "Singapore", "Asia/Singapore"),
                ("🇹🇭", "Thailand", "Asia/Bangkok"),
            ],
            "Europe": [
                ("🇫🇷", "France", "Europe/Paris"),
                ("🇩🇪", "Germany", "Europe/Berlin"),
                ("🇬🇷", "Greece", "Europe/Athens"),
                ("🇮🇹", "Italy", "Europe/Rome"),
                ("🇳🇱", "Netherlands", "Europe/Amsterdam"),
                ("🇷🇺", "Russia (Moscow)", "Europe/Moscow"),
                ("🇪🇸", "Spain", "Europe/Madrid"),
                ("🇬🇧", "United Kingdom", "Europe/London"),
            ],
            "America": [
                ("🇦🇷", "Argentina", "America/Argentina/Buenos_Aires"),
                ("🇧🇷", "São Paulo", "America/Sao_Paulo"),
                ("🇨🇦", "Toronto", "America/Toronto"),
                ("🇨🇦", "Vancouver", "America/Vancouver"),
                ("🇨🇦", "Montreal", "America/Toronto"),
                ("🇨🇦", "Calgary", "America/Edmonton"),
                ("🇲🇽", "Mexico City", "America/Mexico_City"),
                ("🇺🇸", "New York", "America/New_York"),
                ("🇺🇸", "Chicago", "America/Chicago"),
                ("🇺🇸", "Denver", "America/Denver"),
                ("🇺🇸", "Los Angeles", "America/Los_Angeles"),
            ],
        }
        self.update_world_clock.start()  # start the auto-update task

    async def cog_unload(self) -> None:
        self.update_world_clock.cancel()  # stop task if cog unloads


    def build_description(self):
        """Build the full description with all continents and times."""
        description = (
            "✨ **“Prepare for trouble, and make it timely!”**\n"
            "Jessie, James, and Meowth bring you world time zones so you’ll never be late for your next scheme! 🕰️\n\n"
            "🗺️ Villainy never sleeps, and neither do our clocks!\n"
            "Got a country or city you’d like added?\n"
            "👉 Don’t hesitate to contact us or tag Jessie, James, or Meowth — we’re always plotting updates! 😼\n\n"
        )
        for continent, countries in self.timezones.items():
            lines = []
            for flag, city, tz_name in countries:
                tz = pytz.timezone(tz_name)
                now = datetime.now(tz)
                date_str = now.strftime("%Y-%m-%d")
                time_str = now.strftime("%I:%M %p")
                # Align names for neat display
                lines.append(f"{flag} {city:<18} 📅 {date_str} 🕒 {time_str}")
            description += f"🌏 **{continent.upper()}**\n```\n" + "\n".join(lines) + "\n```\n"
        return description

    @tasks.loop(minutes=1)
    async def update_world_clock(self):
        """Update the single embed every 1 minute."""
        if not self.channel_id or not self.clock_message_id:
            return
        channel = self.bot.get_channel(self.channel_id)
        if not channel:
            return
        try:
            message = await channel.fetch_message(self.clock_message_id)
            description = self.build_description()
            embed = Embed(
                title="🕰️ Rocket Global Time Monitor",
                description=description,
                color=0x9b59b6
            )
            await message.edit(embed=embed)
        except Exception as e:
            print(f"[WorldClock] Failed to update embed: {e}")

    @app_commands.command(
        name="rocket-world-clock",
        description="🕒🌏 Show all continents in a single world clock embed (Admins only)"
    )
    async def rocket_world_clock(self, interaction: Interaction):
        """Post the world clock embed for the first time (Admins only)."""
        # Safe admin check
        if not interaction.guild:  # fallback if used in DMs
            await interaction.response.send_message(
                "❌ This command can only be used in a server.", ephemeral=True
            )
            return

        member = interaction.guild.get_member(interaction.user.id)
        if not member or not member.guild_permissions.administrator:
            await interaction.response.send_message(
                "🚫 Only admins can use this command.", ephemeral=True
            )
            return



        description = self.build_description()
        embed = Embed(
            title="🕒🌏 Rocket Global Time Monitor",
            description=description,
            color=0x9b59b6
        )
        await interaction.response.send_message(embed=embed)
        message = await interaction.original_response()
        self.clock_message_id = message.id
        self.channel_id = interaction.channel_id

async def setup(bot):
    await bot.add_cog(WorldClock(bot))
