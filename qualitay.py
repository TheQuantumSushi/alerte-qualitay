import discord
from discord.ext import tasks, commands
from discord import app_commands
import yaml
import os
import logging
from yt_dlp import YoutubeDL

# Create a logging instance :

logger = logging.getLogger(__name__)

# Define all the functions that will be used by the commands :

def load_config():
    """
    Load the configuration file (config.yaml), which lists
    all the monitored youtube channels

    Args:
        None

    Returns:
        - dict: The configuration dictionary loaded from config.yaml
    """
    with open("config.yaml", "r") as f:
        return yaml.safe_load(f)

def load_cache():
    """
    Load the cache file (cache.yaml), which stores the
    videos that have already been posted to avoid
    duplicates, as well as which channels are users following

    Args:
        None

    Returns:
        - dict: The cache dictionary loaded from cache.yaml
    """
    with open("cache.yaml", "r") as f:
        return yaml.safe_load(f)

def save_cache(cache):
    """
    Save the cache file (cache.yaml)

    Args:
        - cache [dict]: The cache dictionary to save

    Returns:
        None
    """
    with open("cache.yaml", "w") as f:
        yaml.safe_dump(cache, f)

def reset_cache(reset_type = "all"):
    """
    Reset the cache file (cache.yaml), either partially or
    entirely. Different values for the reset_type argument are
    possible :
    - videos : reset the last monitored videos
    - subscriptions : reset the users' follows
    - all : reset both

    Args:
        - reset_type [str]: Type of reset to perform (default: "all")

    Returns:
        - dict: The newly reset cache dictionary
    """

    if reset_type == "videos":
        empty_cache = {"videos": {}, "subscriptions": load_cache().get("subscriptions", {})}
    elif reset_type == "subscriptions":
        empty_cache = {"videos": load_cache().get("videos", {}), "subscriptions": {}}
    else:
        empty_cache = {"videos": {}, "subscriptions": {}}

    save_cache(empty_cache)

    return empty_cache

def get_latest_video(channel_url):
    """
    Grab the last video from a YouTube channel URL using yt-dlp,
    extract infos (id, title, url and channel name) and return them
    in a dictionnary

    Args:
        - channel_url [str]: The YouTube channel URL to fetch from

    Returns:
        - dict: Dictionary containing video info (id, title, url, channel_name)
        - None: If no valid video is found or an error occurs
    """
    # Ensure we're fetching from the /videos page to get uploads in chronological order
    if not channel_url.endswith('/videos'):
        fetch_url = channel_url.rstrip('/') + '/videos'
    else:
        fetch_url = channel_url

    ydl_opts = {
        "quiet": False,
        "skip_download": True,
        "playlist_items": "1",  # Only get the first video from the list
        "ignoreerrors": True,   # Continue on errors
    }

    try:
        with YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(fetch_url, download=False)

            if "entries" in result and result["entries"]:
                # The first entry should be the latest video (yt-dlp returns chronologically)
                for entry in result["entries"]:
                    if not entry:  # Skip None entries
                        continue

                    video_id = entry.get('id')
                    webpage_url = entry.get('webpage_url', '')

                    # Verify this is an actual video
                    if video_id and '/watch?v=' in webpage_url:
                        return {
                            "id": video_id,
                            "title": entry.get('title', 'Unknown Title'),
                            "url": webpage_url,
                            "channel_name": entry.get('uploader', 'Unknown Channel')
                        }

    except Exception as e:
        print(f"Error fetching video for {channel_url}: {e}")

    return None

def has_role(interaction, role):
    """
    Check if a user has a certain discord role

    Args:
        - interaction [discord.Interaction]: The Discord interaction object
        - role [str]: The role name to check for

    Returns:
        - bool: True if user has the role, False otherwise
    """
    return any(user_role.name == role for user_role in interaction.user.roles)

# Define all the commands :

class ChannelCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ADD :
    @app_commands.command(name = "add", description = "[ADMIN] Ajouter une chaîne à la liste de monitoring")
    async def add(self, interaction: discord.Interaction, channel_url: str):
        """
        Add a YouTube channel to the list of monitored channels, by adding
        the URL argument to the config.yaml file

        Args:
            - interaction [discord.Interaction]: The Discord interaction object
            - channel_url [str]: The YouTube channel URL to add

        Returns:
            None
        """

        # This is an admin-only command, notify the user they don't have the permission if they don't have the Admin role :
        if not has_role(interaction, "Admin"):
            await interaction.response.send_message("Vous n'avez pas la permission d'utiliser cette commande.", ephemeral = True)
            return

        await interaction.response.defer() # acknowledge interaction

        # Notify the user if the URL is valid :
        if "youtube.com" not in channel_url:
            await interaction.followup.send("Lien YouTube invalide", ephemeral = True)
            return

        # Notify the user if the channel is already monitored :
        if channel_url in self.bot.config.get("channels", []):
            await interaction.followup.send("La chaîne est déjà monitorée", ephemeral = True)
            return

        # Fetch latest video and add it to cache to prevent notification on next scan :
        latest_video = get_latest_video(channel_url)

        # Update configuration and cache files :
        self.bot.config["channels"].append(channel_url)
        with open("config.yaml", "w") as f:
            yaml.safe_dump(self.bot.config, f)

        if latest_video:
            self.bot.cache["videos"][channel_url] = latest_video["id"]
            save_cache(self.bot.cache)

        # Send confirmation message :
        await interaction.followup.send(f"Chaîne ajoutée : {channel_url}")

    # REMOVE :
    @app_commands.command(name = "remove", description = "[ADMIN] Retirer une chaîne de la liste de monitoring")
    async def remove(self, interaction: discord.Interaction, index: int):
        """
        Remove a channel from the list of monitored channels, using its index
        (which can be seen using command /channels)

        Args:
            - interaction [discord.Interaction]: The Discord interaction object
            - index [int]: The channel index to remove

        Returns:
            None
        """

        # This is an admin-only command, notify the user they don't have the permission if they don't have the Admin role :
        if not has_role(interaction, "Admin"):
            await interaction.response.send_message("Vous n'avez pas la permission d'utiliser cette commande", ephemeral=True)
            return

        # Notify the user if the index is invalid :
        channels = self.bot.config.get("channels", [])
        if index < 1 or index > len(channels):
            await interaction.response.send_message("Numéro de chaîne invalide", ephemeral=True)
            return

        # Get the channel URL and linked videos :
        channel_url = channels[index - 1]
        videos = self.bot.cache.get("videos", {})

        # Remove the channel from the configuration :
        self.bot.config["channels"].remove(channel_url)
        with open("config.yaml", "w") as f:
            yaml.safe_dump(self.bot.config, f)

        # Remove the channel's videos from videos cache :
        if channel_url in videos:
            del videos[channel_url]
            save_cache(self.bot.cache)

        # Send confirmation message :
        await interaction.response.send_message(f"Chaîne retirée : {channel_url}", ephemeral=True)

    # RESET-CACHE :
    @app_commands.command(name="reset-cache", description = "[ADMIN] Nettoyer le cache (options : all, videos, subscriptions)")
    @app_commands.choices(reset_type = [
        app_commands.Choice(name="All", value = "all"),
        app_commands.Choice(name="Videos", value = "videos"),
        app_commands.Choice(name="Subscriptions", value = "subscriptions"),
    ])
    async def reset_cache_command(self, interaction: discord.Interaction, reset_type: app_commands.Choice[str]):
        """
        Reset the cache, either partially (only videos or subscriptions) or entirely (both).
        Only three arguments are therefore defined for the command : all, videos and subscriptions

        Args:
            - interaction [discord.Interaction]: The Discord interaction object
            - reset_type [app_commands.Choice[str]]: The type of reset to perform

        Returns:
            None
        """

        # This is an admin-only command, notify the user they don't have the permission if they don't have the Admin role :
        if not has_role(interaction, "Admin"):
            await interaction.response.send_message("Vous n'avez pas la permission d'utiliser cette commande.", ephemeral=True)
            return

        # Use the dedicated function to reset the cache :
        self.bot.cache = reset_cache(reset_type.value)

        # Send confirmation message :
        await interaction.response.send_message(f"Le cache a été nettoyé ({reset_type.name.lower()}).", ephemeral=True)

    # PURGE-CHANNEL :
    @app_commands.command(name = "purge-channel", description = "[ADMIN] Supprimer un certain nombre de messages dans ce salon (0 pour tous)")
    @commands.has_permissions(manage_messages = True) # allow the command to manage (i.e. delete) messages
    async def purge_message(self, interaction: discord.Interaction, count: int):
        """
        Delete the last n messages in the channel (0 for all (actually 1000, which is the maximum))

        Args:
            - interaction [discord.Interaction]: The Discord interaction object
            - count [int]: Number of messages to delete (0 for maximum)

        Returns:
            None
        """

        # This is an admin-only command, notify the user they don't have the permission if they don't have the Admin role :
        if not has_role(interaction, "Admin"):
            await interaction.response.send_message("Vous n'avez pas la permission d'utiliser cette commande.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral = True)
        # Handle errors if the bot doesn't have correct permissions to delete messages :
        if not interaction.channel.permissions_for(interaction.guild.me).manage_messages:
            await interaction.followup.send("Permissions insuffisantes pour supprimer des messages", ephemeral=True)
            return

        # If argument is 0, delete the maximum number of messages (1000), else delete the specified count :
        count = 1000 if count == 0 else min(count, 1000)

        # Delete the messages :
        deleted = await interaction.channel.purge(limit = count)

        # Send confirmation message :
        await interaction.followup.send(f"{len(deleted)} messages supprimés", ephemeral = True)

    # SCAN :
    @app_commands.command(name = "scan", description = "[ADMIN] Manuellement déclencher la détection de nouvelles vidéos")
    async def scan(self, interaction: discord.Interaction):
        """
        Manually trigger the scan for new videos, which is defined after in the method
        "check_videos" of the bot class

        Args:
            - interaction [discord.Interaction]: The Discord interaction object

        Returns:
            None
        """

        # This is an admin-only command, notify the user they don't have the permission if they don't have the Admin role :
        if not has_role(interaction, "Admin"):
            await interaction.response.send_message("Vous n'avez pas la permission d'utiliser cette commande.", ephemeral=True)
            return

        await interaction.response.send_message("Scan de nouvelles vidéos en cours...", ephemeral = True)
        await self.bot.check_videos() # call the method to perform the scan

        # Send confirmation message once the scan is done :
        await interaction.followup.send("Scan de nouvelles vidéos terminé", ephemeral = True)

    # CHANNELS :
    @app_commands.command(name = "channels", description = "Lister les chaînes monitorées")
    async def sub_list(self, interaction: discord.Interaction):
        """
        Lists all monitored channel with their index numbers

        Args:
            - interaction [discord.Interaction]: The Discord interaction object

        Returns:
            None
        """

        # Get the channels :
        channels = self.bot.config.get("channels", [])

        # Notify the user if there are no channels currently monitored :
        if not channels:
            await interaction.response.send_message("Aucune chaîne monitorée actuellement", ephemeral = True)
            return

        # Create the message :
        message = "\n".join([f"{i + 1}. {ch.split('@')[-1]}" for i, ch in enumerate(channels)])

        # Send the message :
        await interaction.response.send_message(f"**Chaînes monitorées :**\n{message}", ephemeral = True)

    # FOLLOW :
    @app_commands.command(name = "follow", description="Suivre une chaîne pour être mentionné lors de nouvelles vidéos")
    async def sub(self, interaction: discord.Interaction, index: int):
        """
        Allow a user to follow a channel (using its index), which will make the bot ping the
        user when there is a new video of this channel. The followed channels are stored
        in the cache file under "subscriptions"

        Args:
            - interaction [discord.Interaction]: The Discord interaction object
            - index [int]: The channel index to follow

        Returns:
            None
        """

        # Get the channels :
        channels = self.bot.config.get("channels", [])

        # Notify the user if the channel index is invalid :
        if index < 1 or index > len(channels):
            await interaction.response.send_message("Numéro de chaîne invalide", ephemeral = True)
            return

        # Grab the channel's URL and the user ID, and store them in the cache :
        channel_url = channels[index - 1]
        user_id = str(interaction.user.id)

        if user_id not in self.bot.cache["subscriptions"]:
            self.bot.cache["subscriptions"][user_id] = []

        if channel_url not in self.bot.cache["subscriptions"][user_id]:
            self.bot.cache["subscriptions"][user_id].append(channel_url)
            save_cache(self.bot.cache)

        # Send confirmation message :
        await interaction.response.send_message(f"Vous êtes maintenant abonné à : {channel_url.split('@')[-1]}", ephemeral = True)

    # UNFOLLOW :
    @app_commands.command(name = "unfollow", description = "Ne plus suivre une chaîne")
    async def unsub(self, interaction: discord.Interaction, index: int):
        """
        Allow a user to unfollow a channel

        Args:
            - interaction [discord.Interaction]: The Discord interaction object
            - index [int]: The channel index to unfollow

        Returns:
            None
        """

        # Get the channels :
        channels = self.bot.config.get("channels", [])

        # Notify the user if the channel index is invalid :
        if index < 1 or index > len(channels):
            await interaction.response.send_message("Numéro de chaîne invalide", ephemeral = True)
            return

        # Grab the channel's URL and the user ID, and remove them from the cache :
        channel_url = channels[index - 1]
        user_id = str(interaction.user.id)

        if user_id in self.bot.cache["subscriptions"] and channel_url in self.bot.cache["subscriptions"][user_id]:
            self.bot.cache["subscriptions"][user_id].remove(channel_url)
            save_cache(self.bot.cache)
            # Send confirmation message :
            await interaction.response.send_message(f"Vous n'êtes plus abonné à : {channel_url.split('@')[-1]}", ephemeral = True)
        else:
            # Notify the user if they weren't following the channel in the first place :
            await interaction.response.send_message("Vous ne suiviez pas cette chaîne", ephemeral = True)

    # MY-SUBS :
    @app_commands.command(name = "my-subs", description = "Afficher mes chaînes suivies")
    async def my_subs(self, interaction: discord.Interaction):
        """
        Allow a user to see which channels they are following, with their indexes

        Args:
            - interaction [discord.Interaction]: The Discord interaction object

        Returns:
            None
        """

        # Get the user ID and followed channels :
        user_id = str(interaction.user.id)
        user_subscriptions = self.bot.cache["subscriptions"].get(user_id, [])

        # Notify the user if they aren't following any channels :
        if not user_subscriptions:
            await interaction.response.send_message("Vous ne suivez aucune chaîne", ephemeral = True)
            return

        # Get the channels to extract their names from their urls (https://www.youtube.com/@XXX -> extract XXX)
        channels = self.bot.config.get("channels", [])
        subscription_info = []

        for i, channel_url in enumerate(channels):
            if channel_url in user_subscriptions:
                subscription_info.append(f"{i + 1}. {channel_url.split('@')[-1]} (ID: {channel_url})")
        if subscription_info:
            message = "\n".join(subscription_info)
            # Send the message :
            await interaction.response.send_message(f"**Vous suivez les chaînes :**\n{message}", ephemeral = True)
        else:
            # Notify the user if they aren't following any channels :
            await interaction.response.send_message("Vous ne suivez aucune chaîne", ephemeral = True)

# Create the bot class :

class YouTubeBot(commands.Bot):
    def __init__(self, cache, config, *args, **kwargs):
        """
        Initialize the YouTube monitoring bot

        Args:
            - cache [dict]: The cache dictionary
            - config [dict]: The configuration dictionary
            - *args: Additional positional arguments for commands.Bot
            - **kwargs: Additional keyword arguments for commands.Bot

        Returns:
            None
        """
        super().__init__(*args, **kwargs)
        self.config = config
        self.dis_chan = int(os.getenv("DISCORD_CHANNEL_ID"))
        self.cache = cache

    async def setup_hook(self):
        """
        Setup the channel cog and sync the command tree

        Args:
            None

        Returns:
            None
        """
        await self.add_cog(ChannelCog(self))
        await self.tree.sync()

    async def on_ready(self):
        """
        Start task loop when ready

        Args:
            None

        Returns:
            None
        """
        logger.error(f"Logged in as {self.user}")
        if not self.check_videos.is_running():
            self.check_videos.start()

    @tasks.loop(hours = 1)
    async def check_videos(self):
        """
        Check if there are new, non-cached videos for the monitored channels that
        are stored in config.yaml. If there are, send a message to the channel
        (specified by the environment variable DISCORD_CHANNEL_ID, loaded in the variable
        dis_chan), to notify users of the release

        Args:
            None

        Returns:
            None
        """

        for channel in self.config["channels"]:
            latest_video = get_latest_video(channel) # use the already defined function to grab the latest video for the channel
            if not latest_video:
                continue

            # Check if it is the same as the cached latest video of this channel :
            cached_video_id = self.cache["videos"].get(channel)
            if cached_video_id == latest_video["id"]:
                continue

            # If it isn't, then cache it :
            self.cache["videos"][channel] = latest_video["id"]
            save_cache(self.cache)

            # Send the message in the discord channel :
            discord_channel = self.get_channel(self.dis_chan)
            if discord_channel:

                # Create the string of discord mentions for all the users that are following this channel :
                mentions = [f"<@{user}>" for user, subs in self.cache["subscriptions"].items() if channel in subs]
                mentions_str = " ".join(mentions) if mentions else ""

                # Create the message :
                message = (
                    "# Alerte Qualitaÿ !\n"
                    f"  ├ Par : {latest_video['channel_name']}\n"
                    f"  └ Titre : {latest_video['title']}\n"
                    "-----------------------------------------------------\n"
                    f"Lien : {latest_video['url']}\n"
                    "-----------------------------------------------------"
                )

                # Append to it the string of mentions if it isn't empty :
                if mentions_str:
                    message += f"\nMentions abonnés : {mentions_str}\n" + "-----------------------------------------------------"
                
                # Send the message :
                await discord_channel.send(message)

if __name__ == "__main__":

    # Get the bot token from the environment variable :
    discord_bot_token = os.getenv("DISCORD_BOT_TOKEN")
    if not discord_bot_token:
        print("Error: DISCORD_BOT_TOKEN environment variable is not set.")
        exit(1)

    # Initialize and run the bot :
    intents = discord.Intents.default() # initializes a default set of Discord Gateway Intents (a way to request specific event data from the API)
    bot = YouTubeBot(load_cache(), load_config(), command_prefix="!", intents = intents)
    bot.run(discord_bot_token)
