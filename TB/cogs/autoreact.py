import discord
from discord.ext import commands

class AutoReact(commands.Cog):
    """Automatically reacts to messages in a specific channel."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.target_channel_id = 1399455904314822677  # Replace with your channel ID
        self.emoji_id = 1406998026001715234  # Replace with your custom emoji ID

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Automatically react to messages in the target channel."""
        # Check if the message is in the specified channel and isn't from the bot itself
        if message.channel.id == self.target_channel_id and message.author != self.bot.user:
            try:
                # Create the emoji using its ID
                emoji = discord.utils.get(self.bot.emojis, id=self.emoji_id)
                if emoji:
                    await message.add_reaction(emoji)  # Add the reaction using the emoji ID
            except discord.DiscordException as e:
                print(f"Failed to react: {e}")

    # Optionally: To ensure the bot reacts to messages from webhooks too:
    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        """React to edited messages as well."""
        if after.channel.id == self.target_channel_id and after.author != self.bot.user:
            try:
                # Create the emoji using its ID
                emoji = discord.utils.get(self.bot.emojis, id=self.emoji_id)
                if emoji:
                    await after.add_reaction(emoji)  # Add the reaction using the emoji ID
            except discord.DiscordException as e:
                print(f"Failed to react: {e}")

async def setup(bot: commands.Bot):
    await bot.add_cog(AutoReact(bot))
