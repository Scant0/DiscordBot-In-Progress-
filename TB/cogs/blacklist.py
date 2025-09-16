import discord
from discord.ext import commands
from discord import app_commands
import json
import os

BLACKLIST_FILE = "blacklist.json"

class BlacklistWords(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.blacklisted_words = self.load_blacklist()

    # -----------------
    # File I/O Helpers
    # -----------------
    def load_blacklist(self):
        if os.path.exists(BLACKLIST_FILE):
            with open(BLACKLIST_FILE, "r") as f:
                return set(json.load(f))
        return set()

    def save_blacklist(self):
        with open(BLACKLIST_FILE, "w") as f:
            json.dump(list(self.blacklisted_words), f, indent=4)

    # -----------------
    # Message listener
    # -----------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        for word in self.blacklisted_words:
            if word.lower() in message.content.lower():
                try:
                    await message.delete()
                    await message.channel.send(
                        f"{message.author.mention}, that word is not allowed here.",
                        delete_after=2
                    )
                except discord.Forbidden:
                    print("⚠️ Missing permission to delete messages.")
                except discord.HTTPException:
                    print("⚠️ Failed to delete message.")
                break

    # -----------------
    # Slash Commands
    # -----------------
    @app_commands.command(name="blacklist_add", description="Add a word to the blacklist")
    @app_commands.checks.has_permissions(administrator=True)
    async def blacklist_add(self, interaction: discord.Interaction, word: str):
        self.blacklisted_words.add(word.lower())
        self.save_blacklist()
        await interaction.response.send_message(
            f"✅ Added **{word}** to the blacklist.", ephemeral=True
        )

    @app_commands.command(name="blacklist_remove", description="Remove a word from the blacklist")
    @app_commands.checks.has_permissions(administrator=True)
    async def blacklist_remove(self, interaction: discord.Interaction, word: str):
        if word.lower() in self.blacklisted_words:
            self.blacklisted_words.remove(word.lower())
            self.save_blacklist()
            await interaction.response.send_message(
                f"✅ Removed **{word}** from the blacklist.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"⚠️ **{word}** is not in the blacklist.", ephemeral=True
            )

    @app_commands.command(name="blacklist_show", description="Show all blacklisted words")
    @app_commands.checks.has_permissions(administrator=True)
    async def blacklist_show(self, interaction: discord.Interaction):
        if self.blacklisted_words:
            words = ", ".join(self.blacklisted_words)
            await interaction.response.send_message(
                f"🚫 Blacklisted words: **{words}**", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "✅ No words are currently blacklisted.", ephemeral=True
            )

async def setup(bot):
    await bot.add_cog(BlacklistWords(bot))
