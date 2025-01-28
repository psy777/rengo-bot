import os
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timedelta
import logging
import sgfengine
import cairosvg
from datetime import datetime
import json
import uuid

class RengoCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config = bot.config

    @app_commands.command(name="help", description="Shows the help menu")
    async def help(self, interaction: discord.Interaction):
        settings = self.config.get_server_settings(interaction.guild_id)
        if interaction.channel_id not in settings["permitted_channel_ids"]:
            return

        help_message = {
            "/help": "shows this help",
            "/play": "play a move. For example, `/play Q16`. Passing is not implemented!",
            "/edit": "if you make a mistake in your move, you have 5 minutes to correct it",
            "/sgf": "get the SGF file of the game",
            "/board": "shows the current board",
            "/newgame": "starts a game in this channel",
            "/resign": "resigns the game for the specified color"
        }

        embed = discord.Embed(title="RengoBot Help", description="List of available commands:", color=discord.Color.blue())
        for command, description in help_message.items():
            embed.add_field(name=command, value=description, inline=False)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="newgame", description="Start a new game")
    @app_commands.describe(
        handicap="Number of handicap stones",
        komi="Komi value")
    async def newgame(self, interaction: discord.Interaction, game_type: str = "random", handicap: int = 0, komi: float = 6.5):
        channel_id = str(interaction.channel_id)
    
        # Get current timestamp as a UNIX timestamp
        timestamp = int(datetime.utcnow().timestamp())

        if handicap > 9:
            await interaction.response.send_message("The maximum allowed handicap is 9 stones.")
            handicap = 9

        if channel_id in self.config.state_cache:
            await interaction.response.send_message("A game is already active in this channel!")
            return

        # Generate a UUID for the game
        game_uuid = uuid.uuid4()

        # Create the SGF file
        sgf_file_name = f"{channel_id}_{game_uuid}.sgf"
        sgfengine.new_game(channel_id, handicap, komi)  # Assuming this generates and saves an SGF file

        # Create the metadata JSON file
        metadata = {
            "timestamp": timestamp
        }
        json_file_name = f"{channel_id}_{game_uuid}.json"
        with open(json_file_name, 'w') as json_file:
            json.dump(metadata, json_file, indent=4)

        # Send initialization message and starting board
        await interaction.response.send_message(f"A new game has been started!")
        await self.board(interaction)

    @app_commands.command(name="play", description="Play a move")
    @app_commands.describe(move="The move to play (e.g. Q16)")
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def play(self, interaction: discord.Interaction, move: str):

        channel_id = str(interaction.channel_id)
        user = interaction.user

        if channel_id not in self.config.state_cache:
            await interaction.response.send_message("No active game in this channel!")
            return

        game_state = self.config.state_cache[channel_id]

        try:
            sgfengine.play_move(channel_id, move, user.display_name)
            logging.info(f"Move played by {user.id}: {move} in channel {channel_id}.")
        except ValueError as e:
            logging.warning(f"Invalid move by {user.id}: {e}")
            await interaction.response.send_message(str(e))
            return

    @app_commands.command(name="board", description="Show the current board state")
    async def board(self, interaction: discord.Interaction):

        channel_id = str(interaction.channel_id)

        if channel_id not in self.config.state_cache:
            await interaction.response.send_message("No active game in this channel!")
            return

        game_state = self.config.state_cache[channel_id]

        # Render board to SVG and convert to PNG
        svg_filename = f"{channel_id}.svg"
        png_filename = f"{channel_id}.png"
        sgfengine.render_sgf_to_svg(channel_id)
        cairosvg.svg2png(url=svg_filename, write_to=png_filename, dpi=300, output_width=800, output_height=800)

        # Send PNG and clean up temp files
        file = discord.File(png_filename)
        try:
            os.remove(svg_filename)
            os.remove(png_filename)
        except OSError as e:
            logging.error(f"Error cleaning up files: {e}")
        next_player_id = game_state["teams"]["white"][0] if game_state["teams"]["white"] else None

        if next_player_id:
            next_player = await interaction.guild.fetch_member(next_player_id)
            await interaction.response.send_message(file=file, content=f"{next_player.display_name}'s turn! ⭐")
        else:
            await interaction.response.send_message(file=file, content="Waiting for players to join!")

    @app_commands.command(name="sgf", description="Get the SGF file of the current game")
    async def sgf(self, interaction: discord.Interaction):

        channel_id = str(interaction.channel_id)
        file = discord.File(f"{channel_id}.sgf")
        await interaction.response.send_message(file=file)

    @app_commands.command(name="edit", description="Edit your last move")
    @app_commands.describe(move="The new move to play (e.g. Q16)")
    async def edit(self, interaction: discord.Interaction, move: str):

        channel_id = str(interaction.channel_id)
        user = interaction.user

        if channel_id not in self.config.state_cache:
            await interaction.response.send_message("No active game in this channel!")
            return

        game_state = self.config.state_cache[channel_id]
        last_moves = game_state.get("last_times", [])

        if not last_moves or game_state["players"][-1] != user.id or datetime.now() - datetime.fromisoformat(last_moves[-1]) > timedelta(minutes=5):
            await interaction.response.send_message("You cannot edit this move!")
            return

        if not sgfengine.is_valid_move(move):
            await interaction.response.send_message("Invalid move! Please use standard Go coordinates like Q16.")
            return

        try:
            sgfengine.play_move(channel_id, move, user.display_name, True)
        except ValueError as e:
            await interaction.response.send_message(str(e))
            return

        game_state["last_move_time"] = datetime.now().isoformat()
        self.config.save_state()

        await self.board(interaction)

    @app_commands.command(name="resign", description="Resign the game for a color")
    @app_commands.describe(color="The color to resign (B for Black, W for White)")
    async def resign(self, interaction: discord.Interaction, color: str):
        settings = self.config.get_server_settings(interaction.guild_id)
        if interaction.user.id not in settings["admins"]:
            await interaction.response.send_message("You don't have permission to use this command!")
            return

        channel_id = str(interaction.channel_id)

        if channel_id not in self.config.state_cache:
            await interaction.response.send_message("No active game in this channel!")
            return

        game_state = self.config.state_cache[channel_id]

        if color.upper() not in ["B", "W"]:
            await interaction.response.send_message("Invalid color! Use `B` for Black or `W` for White.")
            return

        team_color = "black" if color.upper() == "B" else "white"

        # End the game and save SGF
        sgf_file_path = f"{channel_id}.sgf"
        sgfengine.end_game(channel_id, team_color)

        # Send the SGF file
        file = discord.File(sgf_file_path, filename=f"{team_color}_resigned.sgf")
        await interaction.response.send_message(file=file, content=f"Team {team_color.capitalize()} has resigned! Game over.")

        # Remove the game state
        del self.config.state_cache[channel_id]
        self.config.save_state()

        logging.info(f"Game in channel {channel_id} ended with team {team_color} resigning.")

async def setup(bot):
    await bot.add_cog(RengoCog(bot))
