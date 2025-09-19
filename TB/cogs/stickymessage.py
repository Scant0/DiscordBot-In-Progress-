import discord
from discord.ext import commands
import asyncio

class StickyMessage(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.sticky_message = None  # Stores the ID of the sticky message
        self.last_message_time = None  # Track the time of the last message

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """
        Listens for new messages in all channels.
        When a message is sent in the specified channel, the bot posts a sticky message
        and deletes any previous sticky message.
        """
        if message.author == self.bot.user:
            return  # Prevent the bot from reacting to its own messages

        # Specify the channel you want the sticky message to appear in
        target_channel_id = 123456789123456789  # Replace with your target channel ID
        target_channel = self.bot.get_channel(target_channel_id)

        # Check if the message is in the target channel
        if message.channel == target_channel:
            # If the last message is within 7 seconds, ignore this message
            if self.last_message_time and (message.created_at - self.last_message_time).total_seconds() < 7:
                return

            # enter the delay time of sticky message , currently its 0
            await asyncio.sleep(0)

            if self.sticky_message:  # If there was a previous sticky message, delete it
                try:
                    await self.sticky_message.delete()
                except discord.NotFound:
                    pass  # In case the message was already deleted

            # Post the sticky message
            sticky_content = "Enter your sticky message here"
            sticky_message = await target_channel.send(sticky_content)

            # Store the ID of the sticky message to manage it later
            self.sticky_message = sticky_message

            # Update the time of the last message processed
            self.last_message_time = message.created_at

    @commands.hybrid_command(name="set_sticky", description="Set a custom sticky message")
    async def set_sticky(self, ctx, *, message: str):
        """
        Allows an admin to set a custom sticky message in the target channel.
        """
        target_channel_id = 12345678912345567  # Replace with your target channel ID
        target_channel = self.bot.get_channel(target_channel_id)

        if message:
            if self.sticky_message:  # If there's an existing sticky message, delete it
                try:
                    await self.sticky_message.delete()
                except discord.NotFound:
                    pass

            # Post the new sticky message
            sticky_message = await target_channel.send(message)
            self.sticky_message = sticky_message
            await ctx.send(f"Sticky message set to: {message}")
        else:
            await ctx.send("Please provide a message for the sticky text.")

async def setup(bot):
    await bot.add_cog(StickyMessage(bot))
