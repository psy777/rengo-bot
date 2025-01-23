from discord.ext import commands
import discord
import logging
import sgfengine
from datetime import datetime

# Assume these are imported or initialized elsewhere
config = None
bot = commands.Bot(command_prefix='$', help_command=None)

# Utility Functions
async def get_next_player(ctx, game_state, color):
    next_player_id = game_state["teams"][color][0]
    return config.member_cache.get(next_player_id) or await ctx.guild.fetch_member(next_player_id)

def is_channel_permitted(channel_id, settings):
    return channel_id in settings["permitted_channel_ids"]

def is_player_in_queue(game_state, user_id):
    return user_id in game_state["players"]

# Commands
@bot.command()
async def help(ctx):
    settings = config.get_server_settings(ctx.guild.id)
    if ctx.channel.id not in settings["permitted_channel_ids"]:
        return

    help_message = {
        "$help": "shows this help",
        "$join": "join the game in this channel",
        "$leave": "leave the game in this channel",
        "$play <move>": "play a move. For example, `$play Q16`. Passing is not implemented!",
        "$edit <move>": "if you make a mistake in your move, you have 5 minutes to correct it with this command",
        "$sgf": "get the SGF file of the game",
        "$board": "shows the current board",
        "$queue": "get the queue of players",
        "$newgame <queue/random/teachers> <handicap> <komi>": "starts a game in this channel (admin only!)",
        "$resign <B/W>": "<B/W> resigns the game in this channel. It returns its SGF file (admin only!)"
    }

    embed = discord.Embed(title="RengoBot Help", description="List of available commands:", color=discord.Color.blue())
    for command, description in help_message.items():
        embed.add_field(name=command, value=description, inline=False)

    await ctx.send(embed=embed)

@bot.command()
async def newgame(ctx, game_type: str, handicap: int = 0, komi: float = 6.5):
    settings = config.get_server_settings(ctx.guild.id)
    if ctx.author.id not in settings["admins"]:
        await ctx.send("You don't have permission to start a new game!")
        return

    channel_id = str(ctx.channel.id)
    if channel_id in config.state_cache:
        await ctx.send("A game is already active in this channel!")
        return

    sgfengine.new_game(channel_id, handicap, komi)

    game_state = {
        "type": game_type,
        "players": [],
        "last_times": [],
        "teams": {"black": [], "white": []},
        "moves": [],
        "last_move_time": datetime.now().isoformat()
    }

    if game_type == "teachers":
        game_state["teams"]["white"] = settings.get("teachers", [])

    config.state_cache[channel_id] = game_state
    config.save_state()

    if game_type in ["queue", "teachers"]:
        await ctx.send("A new game has started! Join with `$join`.")
    else:
        await ctx.send("A new game has started! Play with `$play <move>`.")

    await board(ctx)

@bot.command()
async def play(ctx, arg):
    settings = config.get_server_settings(ctx.guild.id)
    if not is_channel_permitted(ctx.channel.id, settings):
        return

    channel_id = str(ctx.channel.id)
    user = ctx.author

    if channel_id not in config.state_cache:
        await ctx.send("No active game in this channel!")
        return

    game_state = config.state_cache[channel_id]

    if game_state["type"] == "queue" and not is_player_in_queue(game_state, user.id):
        await ctx.send("Player hasn't joined yet! Join us with `$join`.")
        return

    try:
        sgfengine.play_move(channel_id, arg, user.display_name)
        logging.info(f"Move played by {user.id}: {arg} in channel {channel_id}.")
    except ValueError as e:
        logging.warning(f"Invalid move by {user.id}: {e}")
        await ctx.send(str(e))
        return

    game_state["last_move_time"] = datetime.now().isoformat()
    config.save_state()

    next_player = await get_next_player(ctx, game_state, "white")
    await ctx.send(f"{next_player.mention}'s turn! ⭐")

    config.save_state()

@bot.command()
async def join(ctx):
    settings = config.get_server_settings(ctx.guild.id)
    if not is_channel_permitted(ctx.channel.id, settings):
        return

    channel_id = str(ctx.channel.id)
    user = ctx.author

    if channel_id not in config.state_cache:
        await ctx.send("No active game in this channel!")
        return

    game_state = config.state_cache[channel_id]

    if user.id in game_state["teams"]["black"] or user.id in game_state["teams"]["white"]:
        await ctx.send("Player already in this game!")
        return

    if game_state["type"] == "random":
        await ctx.send("This game has no queue! No need to join, just `$play` whenever you want :P")
        return

    team = "black" if len(game_state["teams"]["black"]) <= len(game_state["teams"]["white"]) else "white"
    if game_state["type"] == "teachers":
        team = "black"

    game_state["teams"][team].append(user.id)
    config.save_state()

    await ctx.send(f"{user.display_name} joined Team {team.capitalize()}!")

@bot.command()
async def leave(ctx):
    settings = config.get_server_settings(ctx.guild.id)
    if not is_channel_permitted(ctx.channel.id, settings):
        return

    channel_id = str(ctx.channel.id)
    user = ctx.author

    if channel_id not in config.state_cache:
        await ctx.send("No active game in this channel!")
        return

    game_state = config.state_cache[channel_id]

    if user.id not in game_state["teams"]["black"] and user.id not in game_state["teams"]["white"]:
        await ctx.send("Player not in this game!")
        return

    team = "black" if user.id in game_state["teams"]["black"] else "white"
    game_state["teams"][team].remove(user.id)
    config.save_state()

    await ctx.send(f"{user.display_name} left Team {team.capitalize()} :(")

@bot.command()
async def board(ctx):
    settings = config.get_server_settings(ctx.guild.id)
    if not is_channel_permitted(ctx.channel.id, settings):
        return

    channel_id = str(ctx.channel.id)

    if channel_id not in config.state_cache:
        await ctx.send("No active game in this channel!")
        return

    game_state = config.state_cache[channel_id]

    # Render board to SVG and convert to PNG
    svg_filename = f"{channel_id}.svg"
    png_filename = f"{channel_id}.png"
    sgfengine.render_sgf_to_svg(channel_id)
    cairosvg.svg2png(url=svg_filename, write_to=png_filename, dpi=300, output_width=800, output_height=800)

    # Send PNG to Discord
    file = discord.File(png_filename)
    next_player_id = game_state["teams"]["white"][0] if game_state["teams"]["white"] else None

    if next_player_id:
        next_player = await ctx.guild.fetch_member(next_player_id)
        await ctx.send(file=file, content=f"{next_player.display_name}'s turn! ⭐")
    else:
        await ctx.send(file=file, content="Waiting for players to join!")

@bot.command()
async def sgf(ctx):
    settings = config.get_server_settings(ctx.guild.id)
    if not is_channel_permitted(ctx.channel.id, settings):
        return

    channel_id = str(ctx.channel.id)
    file = discord.File(f"{channel_id}.sgf")
    await ctx.send(file=file)

@bot.command()
async def queue(ctx):
    settings = config.get_server_settings(ctx.guild.id)
    if not is_channel_permitted(ctx.channel.id, settings):
        return

    channel_id = str(ctx.channel.id)
    guild = ctx.guild

    if channel_id not in config.state_cache:
        await ctx.send("No active game in this channel!")
        return

    game_state = config.state_cache[channel_id]
    color = sgfengine.next_colour(channel_id)

    if game_state["type"] == "random":
        await ctx.send("This game has no queue! No need to join, just `$play` whenever you want :P")
        return

    output = ""
    if game_state["type"] == "teachers":
        output += "Player list for Team Black:\n"
        for idx, player_id in enumerate(game_state["teams"]["black"], 1):
            player_name = (await guild.fetch_member(player_id)).display_name
            output += f"{idx:3}. {player_name}\n"
        await ctx.send(output)
        return

    if not game_state["teams"]["black"] and not game_state["teams"]["white"]:
        output += "Nobody yet! Join us with `$join`"
        await ctx.send(output)
        return

    output += "Player list:\n"
    if not game_state["teams"]["black"]:
        for idx, player_id in enumerate(game_state["teams"]["white"], 1):
            player_name = (await guild.fetch_member(player_id)).display_name
            output += f"⚪ {idx:3}. {player_name}\n"
        output += "\nTeam Black needs more members!"
        await ctx.send(output)
        return

    if not game_state["teams"]["white"]:
        for idx, player_id in enumerate(game_state["teams"]["black"], 1):
            player_name = (await guild.fetch_member(player_id)).display_name
            output += f"⚫ {idx:3}. {player_name}\n"
        output += "\nTeam White needs more members!"
        await ctx.send(output)
        return

    # Combine both teams' queues
    pointers = {"black": 0, "white": 0}
    team_order = ["black", "white"] if color == "black" else ["white", "black"]

    idx = 1
    while True:
        for team in team_order:
            if pointers[team] < len(game_state["teams"][team]):
                player_id = game_state["teams"][team][pointers[team]]
                player_name = (await guild.fetch_member(player_id)).display_name
                stone = "⚫" if team == "black" else "⚪"
                output += f"{stone} {idx:3}. {player_name}\n"
                pointers[team] += 1
                idx += 1

        if all(pointers[team] >= len(game_state["teams"][team]) for team in ["black", "white"]):
            break

    if len(game_state["teams"]["black"]) < 2:
        output += "\nTeam Black needs more members!"
    if len(game_state["teams"]["white"]) < 2:
        output += "\nTeam White needs more members!"

    await ctx.send(output)

@bot.command()
async def edit(ctx, arg):
    settings = config.get_server_settings(ctx.guild.id)
    if not is_channel_permitted(ctx.channel.id, settings):
        return

    channel_id = str(ctx.channel.id)
    user = ctx.author

    if channel_id not in config.state_cache:
        await ctx.send("No active game in this channel!")
        return

    game_state = config.state_cache[channel_id]
    last_moves = game_state.get("last_times", [])

    if not last_moves or game_state["players"][-1] != user.id or datetime.now() - datetime.fromisoformat(last_moves[-1]) > timedelta(minutes=5):
        await ctx.send("You cannot edit this move!")
        return

    legal_moves = [chr(col + ord('A') - 1) + str(row) for col in range(1, 21) if col != 9 for row in range(1, 20)]
    legal_moves += [chr(col + ord('a') - 1) + str(row) for col in range(1, 21) if col != 9 for row in range(1, 20)]
    if arg not in legal_moves:
        await ctx.send("I don't understand the move! Please input it in the format `$play Q16`.")
        return

    try:
        sgfengine.play_move(channel_id, arg, user.display_name, True)
    except ValueError as e:
        await ctx.send(str(e))
        return

    game_state["last_move_time"] = datetime.now().isoformat()
    config.save_state()

    await board(ctx)

@bot.command()
async def resign(ctx, color: str):
    settings = config.get_server_settings(ctx.guild.id)
    if ctx.author.id not in settings["admins"]:
        await ctx.send("You don't have permission to use this command!")
        return

    channel_id = str(ctx.channel.id)

    if channel_id not in config.state_cache:
        await ctx.send("No active game in this channel!")
        return

    game_state = config.state_cache[channel_id]

    if color.lower() not in ["b", "w"]:
        await ctx.send("Invalid color! Use `B` for Black or `W` for White.")
        return

    team_color = "black" if color.lower() == "b" else "white"

    # End the game and save SGF
    sgf_file_path = f"{channel_id}.sgf"
    sgfengine.end_game(channel_id, team_color)

    # Send the SGF file
    file = discord.File(sgf_file_path, filename=f"{team_color}_resigned.sgf")
    await ctx.send(file=file, content=f"Team {team_color.capitalize()} has resigned! Game over.")

    # Remove the game state
    del config.state_cache[channel_id]
    config.save_state()

    logging.info(f"Game in channel {channel_id} ended with team {team_color} resigning.")