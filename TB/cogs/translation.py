import discord
from discord.ext import commands
from googletrans import Translator

class Translation(commands.Cog):
    """Translate messages to English when requested."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.translator = Translator()  # Initialize the Google Translator

    @commands.command(name="translate")
    async def translate(self, ctx: commands.Context):
        """Translate a specific replied message to English."""
        # Check if the user has the admin role
        admin_role_name = "Admin"  # Replace this with your actual admin role name
        if not any(role.name == admin_role_name for role in ctx.author.roles):
            return  # Do nothing if the user does not have the admin role

        # Check if the message is a reply
        if not ctx.message.reference:
            await ctx.send("Please reply to the message you want to translate.")
            return

        # Get the original message being replied to
        original_message = await ctx.channel.fetch_message(ctx.message.reference.message_id)

        # Detect the language of the message
        detected_lang = self.translator.detect(original_message.content).lang

        # If the message is already in English, no need to translate
        if detected_lang == 'en':
            await ctx.send("The message is already in English.")
            return

        # Translate the message to English
        translated = self.translator.translate(original_message.content, src=detected_lang, dest='en')

        # Send the translated message
        await ctx.send(f"**Original: ** {original_message.content}\n**Translated: ** {translated.text}")

async def setup(bot: commands.Bot):
    await bot.add_cog(Translation(bot))
