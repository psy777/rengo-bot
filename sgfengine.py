import os
import json
from sgfmill import sgf
import cairosvg

def convert_svg_to_png(svg_path, png_path, dpi=300, width=800, height=800):
    cairosvg.svg2png(url=svg_path, write_to=png_path, dpi=dpi, output_width=width, output_height=height)

def new_game(channel_name, game_uuid, handicap=0, komi=6.5):
    # Construct file names using channel name and UUID
    base_file_name = f"{channel_name}_{game_uuid}"
    sgf_file = f"{base_file_name}.sgf"
    json_file = f"{base_file_name}.json"
    svg_file = f"{base_file_name}.svg"
    png_file = f"{base_file_name}.png"

    # Initialize a new SGF game
    game = sgf.Sgf_game(19)
    game.root.set("KM", komi)

    if handicap >= 2:
        game.root.set("HA", handicap)

        handicap_dict = {
            2: [(3, 3), (15, 15)],
            3: [(3, 3), (15, 15), (15, 3)],
            4: [(3, 3), (15, 15), (15, 3), (3, 15)],
            5: [(3, 3), (15, 15), (15, 3), (3, 15), (9, 9)],
            6: [(3, 3), (15, 15), (15, 3), (3, 15), (9, 3), (9, 15)],
            7: [(3, 3), (15, 15), (15, 3), (3, 15), (9, 3), (9, 15), (9, 9)],
            8: [(3, 3), (15, 15), (15, 3), (3, 15), (9, 3), (9, 15), (3, 9), (15, 9)],
            9: [(3, 3), (15, 15), (15, 3), (3, 15), (9, 3), (9, 15), (3, 9), (15, 9), (9, 9)]
        }
        game.root.set("AB", handicap_dict[handicap])

    # Save the SGF file
    with open(sgf_file, "wb") as f:
        f.write(game.serialise())

    # Initialize metadata and save to JSON file
    metadata = {
        "current_turn": "B",  # Black always starts
        "handicap": handicap,
        "komi": komi,
        "move_number": 0  # Track the current move number
    }
    with open(json_file, "w") as json_f:
        json.dump(metadata, json_f, indent=4)

    # Render SVG and PNG files
    os.system(f"sgf-render --style fancy --label-sides nesw -o {svg_file} -n last {sgf_file}")
    convert_svg_to_png(svg_file, png_file)

def next_colour(channel_name, game_uuid):
    # Construct the metadata file name
    json_file = f"{channel_name}_{game_uuid}.json"

    # Load metadata
    with open(json_file, "r") as json_f:
        metadata = json.load(json_f)

    # Determine and update the next turn based on move number
    move_number = metadata["move_number"]
    metadata["current_turn"] = "W" if metadata["current_turn"] == "B" else "B"

    # Increment move number
    metadata["move_number"] += 1

    # Save updated metadata
    with open(json_file, "w") as json_f:
        json.dump(metadata, json_f, indent=4)

def play_move(channel_id, messagestr, player, overwrite=False):
    thecol = ord(messagestr[0].lower()) - ord('a')
    if thecol > 8:
        thecol -= 1
    therow = int(messagestr[1:]) - 1

    with open(f"{channel_id}.sgf", "rb") as f:
        game = sgf.Sgf_game.from_bytes(f.read())
    f.close()

    koban = None
    node = game.get_last_node()
    board, moves = sgf_moves.get_setup_and_moves(game)
    if overwrite:
        node2 = node.parent
        node.delete()
        node = node2
        moves = moves[:-1]

    for (colour, (row, col)) in moves:
        koban = board.play(row, col, colour)

    if (therow, thecol) == koban:
        raise ValueError("Ko banned move!")

    colour = "w" if ("B" in node.properties() or "AB" in node.properties()) else "b"

    board2 = board.copy()
    try:
        koban2 = board2.play(therow, thecol, colour)
    except ValueError:
        raise ValueError("Illegal move! There is a stone there.")

    if board2.get(therow, thecol) is None:
        raise ValueError("Illegal move! No self-captures allowed.")

    node2 = node.new_child()
    node2.set(("B" if colour == 'b' else "W"), (therow, thecol))
    if koban2 is not None:
        node2.set("SQ", [koban2])
    node2.set("CR", [(therow, thecol)])
    node2.set("C", player)
    if node.has_property("CR"):
        node.unset("CR")
    if node.has_property("SQ"):
        node.unset("SQ")

    with open(f"{channel_id}.sgf", "wb") as f:
        f.write(game.serialise())
    f.close()

    svg_file = f"{channel_id}.svg"
    png_file = f"{channel_id}.png"
    os.system(f"sgf-render --style fancy --label-sides nesw -o {svg_file} -n last {channel_id}.sgf")
    convert_svg_to_png(svg_file, png_file)

def resign(channel_id, colour, file_name):
    # Open the existing SGF file
    with open(f"{channel_id}.sgf", "rb") as f:
        game = sgf.Sgf_game.from_bytes(f.read())

    # Set the result in the SGF file
    node = game.root
    node.set("RE", ("B" if colour == "W" else "W") + "+R")

    # Write the updated SGF file
    with open(file_name, "wb") as f:
        f.write(game.serialise())

    # Remove the original SGF file
    os.remove(f"{channel_id}.sgf")
