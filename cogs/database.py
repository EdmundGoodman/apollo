import logging
from re import search, sub

from discord import Message
from discord.abc import GuildChannel
from discord.ext.commands import Bot, Cog, Context
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy_utils import ScalarListException

from config import CONFIG
from karma.karma import process_karma
from models import db_session
from models.channel_settings import IgnoredChannel
from models.user import User
from utils import get_database_user, is_compsoc_exec_in_guild, user_is_irc_bot


async def not_in_blacklisted_channel(ctx: Context):
    return (
        await is_compsoc_exec_in_guild(ctx)
        or db_session.query(IgnoredChannel)
        .filter(IgnoredChannel.channel == ctx.channel.id)
        .first()
        is None
    )


class Database(Cog):
    def __init__(self, bot: Bot):
        self.bot = bot
        # Set up a global check that we're not in a blacklisted channel
        self.bot.add_check(not_in_blacklisted_channel)

    @Cog.listener()
    async def on_message(self, message: Message):
        # If the message is by a bot that's not irc then ignore it
        if message.author.bot and not user_is_irc_bot(message):
            return

        user = get_database_user(message.author)
        if not user:
            user = User(user_uid=message.author.id, username=str(message.author))
            db_session.add(user)
        else:
            user.last_seen = message.created_at
        # Commit the session so the user is available now
        try:
            db_session.commit()
        except (ScalarListException, SQLAlchemyError) as e:
            db_session.rollback()
            logging.exception(e)
            # Something very wrong, but not way to reliably recover so abort
            return

        # Only log messages that were in a public channel
        if isinstance(message.channel, GuildChannel):
            # KARMA

            # Get all specified command prefixes for the bot
            command_prefixes = self.bot.command_prefix(self.bot, message)
            # Only process karma if the message was not a command (ie did not start with a command prefix)
            if not any(
                message.content.startswith(prefix) for prefix in command_prefixes
            ):
                # process karma if apropriate
                if search(r"\+\+|--|\+\-", message.content):
                    reply = process_karma(
                        message, message.id, db_session, CONFIG.KARMA_TIMEOUT
                    )
                    if reply:
                        await message.channel.send(reply)
                if "t" in message.content.lower():
                    # if maybe some kind of thanks, process it
                    await self.process_thanks(message)
                if search(r"https?://(twitter\.com|x\.com)", message.content):
                    # if a twitter link, process it
                    send_message = ""
                    sentance = message.content.split(" ")  # split into words
                    for word in sentance:
                        # if any word contains a twitter link replace with fxtwitter
                        if search(r"https?://(twitter\.com|x\.com)", word):
                            send_message += "\n" + sub(
                                r"https?://(twitter\.com|x\.com)",
                                "https://fxtwitter.com",
                                word,
                            )
                    # if there is a message to send, send it
                    if send_message != "":
                        await message.edit(suppress=True)
                        await message.reply(send_message)

    async def process_thanks(self, message: Message):
        # to whoever sees this, you're welcome for the not having a fuck off massive indented if
        if message.author.id == self.bot.user.id:
            # dont thank itself
            return
        # Get the previous message (list comprehension my beloved)
        previous_message = [
            message async for message in message.channel.history(limit=2)
        ][1]
        if message.reference and message.reference.message_id:
            # dont thank replies to something that isnt the bot
            replied_message = await message.channel.fetch_message(
                message.reference.message_id
            )
            if replied_message.author != self.bot.user.id:
                return
        elif (
            previous_message.author.id != self.bot.user.id
            and "apollo" not in message.content.lower()
        ):
            # can only thank replies to bot
            return
        thanks = ["thx", "thanks", "thank you", "ty"]
        # only heart if thanks matches word in message
        if not any(
            search(r"\b" + thank + r"\b", message.content.lower()) for thank in thanks
        ):
            return
        return await message.add_reaction("💜")


async def setup(bot: Bot):
    await bot.add_cog(Database(bot))
