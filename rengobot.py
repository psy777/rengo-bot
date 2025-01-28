import os
import ast
import time
import asyncio
import sgfengine
import discord
from discord import app_commands
import json
import subprocess
import sgfmill
import importlib
import cairosvg
import logging
from datetime import datetime, timedelta
from discord.ext import commands

importlib.reload(sgfengine)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    filename="bot.log",
    filemode="a",
    format="%(asctime)s - %(levelname)s - %(message)s"
)

class BotConfig:
    def __init__(self):
        self.token = ""
        self.server_config = {}
        self.state_cache = {}
        self.member_cache = {}
        self.time_to_skip = timedelta(seconds=86400)
        self.min_time_player = timedelta(seconds=1)
        self.format = "%Y_%m_%d_%H_%M_%S_%f"

    def load_config(self, file_path):
        try:
            with open(file_path, 'r') as file:
                config = json.load(file)
                self.token = config["DISCORD_TOKEN"]  # Require token
                logging.info("Configuration loaded successfully.")
        except FileNotFoundError:
            logging.error("Config file not found. Please ensure 'config.json' exists.")
        except json.JSONDecodeError as e:
            logging.error(f"Invalid JSON in config file: {e}")
        except Exception as e:
            logging.exception("Unexpected error occurred while loading config.")

    def save_state(self, state_file="state.json"):
        try:
            with open(state_file, "w") as file:
                json.dump(self.state_cache, file)
                logging.info("State saved successfully.")
        except Exception as e:
            logging.exception("Failed to save state.")

    def load_state(self, state_file="state.json"):
        try:
            with open(state_file, "r") as file:
                self.state_cache = json.load(file)
                logging.info("State loaded successfully.")
        except FileNotFoundError:
            self.state_cache = {}
            logging.warning("State file not found. Initializing with empty state.")
        except json.JSONDecodeError as e:
            self.state_cache = {}
            logging.error(f"Error reading state.json: {e}")
        except Exception as e:
            self.state_cache = {}
            logging.exception("Unexpected error occurred while loading state.")

config = BotConfig()
config.load_config("config.json")
config.load_state()

intents = discord.Intents.default()
intents.messages = True
intents.members = True

class RengoBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='$', help_command=None, intents=intents)
        self.config = config
        
    async def setup_hook(self):
        try:
            await self.load_extension("cogs.commands")
            await self.tree.sync()
        except commands.ExtensionError as e:
            logging.critical(f"Failed to load extension: {e}")
            raise
        
bot = RengoBot()

async def handle_timeouts():
    guild = discord.utils.get(bot.guilds, name="Awesome Baduk")
    if not guild:
        logging.warning("Guild not found for timeout handler.")
        return

    for channel_id, game_state in config.state_cache.items():
        if not game_state.get("moves"):
            continue

    last_move_time = datetime.fromisoformat(game_state["last_move_time"])
    time_left = last_move_time + config.time_to_skip - datetime.now()

    if time_left < timedelta(seconds=10):
        try:
            next_player_id = game_state["teams"]["white"][0]
            next_player = await guild.fetch_member(next_player_id)
            channel = bot.get_channel(int(channel_id))
            if channel:
                await channel.send(f"{next_player.mention}'s turn! Time is running out!")
            logging.info(f"Warning sent to next player in channel {channel_id}.")
        except discord.errors.DiscordException as e:
            logging.warning(f"Discord error while notifying player in channel {channel_id}: {e}")

@bot.event
async def on_ready():
    guild = discord.utils.get(bot.guilds, id=int(next(iter(config.server_config.keys()), 0)))
    if guild:
        config.member_cache = {member.id: member for member in guild.members}
        logging.info("Member cache initialized.")

@bot.event
async def on_member_join(member):
    if str(member.guild.id) in config.server_config:
        config.member_cache[member.id] = member
        logging.info(f"Member {member.id} added to cache for guild {member.guild.id}.")

@bot.event
async def on_member_remove(member):
    if str(member.guild.id) in config.server_config:
        config.member_cache.pop(member.id, None)
        logging.info(f"Member {member.id} removed from cache for guild {member.guild.id}.")
bot.run(config.token)
