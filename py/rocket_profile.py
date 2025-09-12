import os
import io
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv

load_dotenv()
PROFILE_FORUM_ID = int(os.getenv("PROFILE_FORUM_ID", 0)) if os.getenv("PROFILE_FORUM_ID") else None
DRAWING_SUBMISSION_CHANNEL = int(os.getenv("DRAWING_SUBMISSION_CHANNEL", 0)) if os.getenv("DRAWING_SUBMISSION_CHANNEL") else None

# Example storage for user's drawing submissions (replace with your DB/JSON)
# Format: {user_id: message_id}
user_drawings = {}

class RocketRegistrationForm(discord.ui.Modal, title="🚀 Team Rocket Registration"):
    age = discord.ui.TextInput(label="🎂 Age", placeholder="Must be 18+")
    looking_for = discord.ui.TextInput(label="👀 Looking For", placeholder="💫Age range: , 🌍Location preference:")
    dealbreakers = discord.ui.TextInput(label="🚫 Dealbreakers", placeholder="List your dealbreakers", required=False)
    top_traits = discord.ui.TextInput(label="🫶 Top 3 Traits You Want in a Partner", placeholder="Trait 1, Trait 2, Trait 3", required=False)
    hobbies = discord.ui.TextInput(label="🤭 Hobbies / Fun Fact About You", placeholder="Share something fun!", style=discord.TextStyle.paragraph, required=False)

    async def on_submit(self, interaction: discord.Interaction):
        # 1️⃣ Immediately acknowledge modal so it closes
        await interaction.response.defer(ephemeral=True)

        if PROFILE_FORUM_ID is None:
            await interaction.followup.send(
                "❌ Registration forum channel is not configured. Please tell an admin.",
                ephemeral=True
            )
            return

        forum_channel = interaction.client.get_channel(PROFILE_FORUM_ID)
        if not isinstance(forum_channel, discord.ForumChannel):
            await interaction.followup.send(
                "❌ Forum channel is invalid.",
                ephemeral=True
            )
            return

        # Gather user roles (excluding @everyone)
        roles = [role.mention for role in interaction.user.roles if role.name != "@everyone"]
        roles_display = ", ".join(roles) if roles else "No roles"

        # Build the profile content
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

        # Get the latest drawing attachment from the user
        file_to_attach = None
        if DRAWING_SUBMISSION_CHANNEL:
            try:
                drawing_channel = interaction.client.get_channel(DRAWING_SUBMISSION_CHANNEL)
                if not drawing_channel:
                    print(f"[DEBUG] Drawing channel {DRAWING_SUBMISSION_CHANNEL} not found")
                else:
                    # Fetch recent messages, newest first
                    async for msg in drawing_channel.history(limit=50, oldest_first=False):
                        if msg.author.id == interaction.user.id and msg.attachments:
                            attachment = msg.attachments[0]  # Take the first attachment
                            file_bytes = await attachment.read()
                            file_to_attach = discord.File(
                                fp=io.BytesIO(file_bytes), filename=attachment.filename
                            )
                            print(f"[DEBUG] Found latest drawing: {attachment.filename}")
                            break  # Stop after the latest attachment is found
                    if not file_to_attach:
                        print("[DEBUG] No drawing attachment found for user")
            except Exception as e:
                print(f"[DEBUG] Failed to fetch latest drawing: {e}")
                import traceback
                traceback.print_exc()

        # Thread name
        thread_name = f"Profile: {interaction.user.display_name}"
        existing_threads = [t for t in forum_channel.threads if t.name == thread_name]

        if existing_threads:
            # Update existing thread: edit first message
            thread = existing_threads[0]
            try:
                first_message = await thread.fetch_message(thread.id)
                kwargs = {"content": profile_content}
                if file_to_attach:
                    kwargs["attachments"] = [file_to_attach]
                await first_message.edit(**kwargs)
            except Exception:
                pass
            await interaction.followup.send(
                f"✅ Thanks {interaction.user.display_name}, your profile has been updated!\n"
                f"Check it out here: {thread.jump_url}", ephemeral=True
            )
        else:
            # Create new thread with content and optional attachment
            thread = await forum_channel.create_thread(name=thread_name, content=profile_content)
            if file_to_attach:
                await thread.send(file=file_to_attach)
            await interaction.followup.send(
                f"✅ Thanks {interaction.user.display_name}, you are now registered for Team Rocket matchmaking!\n"
                f"Check your profile here: {thread.jump_url}", ephemeral=True
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
        await interaction.response.send_modal(RocketRegistrationForm())


async def setup(bot: commands.Bot):
    await bot.add_cog(RocketProfileCog(bot))
