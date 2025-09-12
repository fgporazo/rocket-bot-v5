import os
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv

load_dotenv()
PROFILE_FORUM_ID = os.getenv("PROFILE_FORUM_ID")
PROFILE_FORUM_ID = int(PROFILE_FORUM_ID) if PROFILE_FORUM_ID else None


class RocketRegistrationForm(discord.ui.Modal, title="🚀 Team Rocket Registration"):
    age = discord.ui.TextInput(label="Your Age", placeholder="Must be 18+")
    looking_for = discord.ui.TextInput(label="Looking For", placeholder="💫Age range: , 🌍Location preference:")
    dealbreakers = discord.ui.TextInput(label="Dealbreakers", placeholder="List your dealbreakers", required=False)
    top_traits = discord.ui.TextInput(label="Top 3 Traits You Want in a Partner", placeholder="Trait 1, Trait 2, Trait 3", required=False)
    hobbies = discord.ui.TextInput(label="Hobbies / Fun Fact About You", placeholder="Share something fun!", style=discord.TextStyle.paragraph, required=False)

    async def on_submit(self, interaction: discord.Interaction):
        if PROFILE_FORUM_ID is None:
            await interaction.response.send_message(
                "❌ Registration forum channel is not configured. Please tell an admin.",
                ephemeral=True
            )
            return

        # Get the forum channel
        forum_channel = interaction.client.get_channel(PROFILE_FORUM_ID)
        if not isinstance(forum_channel, discord.ForumChannel):
            return

        # Prepare thread name
        thread_name = f"Profile: {interaction.user.display_name}"

        # Check if thread already exists
        existing_threads = [t for t in forum_channel.threads if t.name == thread_name]

        # Gather user roles (excluding @everyone)
        roles = [role.mention for role in interaction.user.roles if role.name != "@everyone"]
        roles_display = ", ".join(roles) if roles else "No roles"

        # Prepare the profile content
        profile_content = (
            f"📋 **My Profile**\n\n"
            f"👤 **User:** {interaction.user.mention}\n"
            f"🔰 Roles: {roles_display}\n"
            f"🎂 Age: {self.age.value}\n"
            f"👀 Looking For: {self.looking_for.value}\n"
            f"🚫 Dealbreakers: {self.dealbreakers.value or 'None'}\n"
            f"🫶 Top 3 traits you want in a partner: {self.top_traits.value or 'None'}\n"
            f"🤭 Hobbies/Fun Fact About You: {self.hobbies.value or 'None'}"
        )

        if existing_threads:
            thread = existing_threads[0]
            try:
                # Update the first message in the existing thread
                first_message = await thread.fetch_message(thread.id)
                await first_message.edit(content=profile_content)
            except Exception:
                pass
            await interaction.response.send_message(
                f"✅ Thanks {interaction.user.display_name}, your profile has been updated! "
                f"Check it out here: {thread.jump_url}",
                ephemeral=True
            )
        else:
            # Create a new thread
            thread = await forum_channel.create_thread(
                name=thread_name,
                content=profile_content
            )

            # Optional: pin the first message
            try:
                first_message = await thread.fetch_message(thread.id)
                await first_message.pin()
            except Exception:
                pass

            await interaction.response.send_message(
                f"✅ Thanks {interaction.user.display_name}, you are now registered for Team Rocket matchmaking! "
                f"Check your profile here: {thread.jump_url}",
                ephemeral=True
            )


class RocketProfileCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="rocket-register", description="Register as a Team Rocket contestant")
    async def rocket_register(self, interaction: discord.Interaction):
        if PROFILE_FORUM_ID is None:
            await interaction.response.send_message(
                "❌ Registration forum channel is not configured. Please tell an admin.",
                ephemeral=True
            )
            return

        # Open the registration modal
        await interaction.response.send_modal(RocketRegistrationForm())


async def setup(bot: commands.Bot):
    await bot.add_cog(RocketProfileCog(bot))
