"""Synthetic parts with known design intent: the answer key for recognition."""

import json
from pathlib import Path

EXAMPLES = Path(__file__).parent.parent / "examples"


def doc(name, parameters, features):
    return {"format": "cadrecipe", "version": "0.1", "name": name, "units": "mm",
            "parameters": parameters, "features": features}


def mounting_plate():
    return json.loads((EXAMPLES / "mounting_plate.cadrecipe.json").read_text())


def bearing_bracket():
    """Chamfered corners, counterbored grid, a row of tapped holes
    dimensioned from the left edge (not symmetric)."""
    return doc(
        "bearing_bracket",
        {"width": 160, "depth": 90, "thickness": 20, "chamfer": 5,
         "cb_margin": 18, "cb_pitch_x": "width - 2*cb_margin",
         "cb_pitch_y": "depth - 2*cb_margin", "row_pitch": 15},
        [
            {"id": "plate", "type": "plate", "width": "width", "depth": "depth",
             "thickness": "thickness", "corners": {"type": "chamfer", "size": "chamfer"}},
            {"id": "fixing", "type": "hole", "spec": {"kind": "counterbore", "size": "M10"},
             "depth": "through",
             "at": {"grid": {"origin": ["cb_margin", "cb_margin"], "count": [2, 2],
                             "pitch": ["cb_pitch_x", "cb_pitch_y"]}}},
            {"id": "row", "type": "hole", "spec": {"kind": "tapped", "size": "M5"},
             "depth": "through",
             "at": {"grid": {"origin": [40, "depth/2"], "count": [3, 1],
                             "pitch": ["row_pitch", 0]}}},
        ],
    )


def odd_plate():
    """Sharp corners, a non-standard hole, a blind pocket and a blind slot."""
    return doc(
        "odd_plate",
        {"width": 100, "depth": 70, "thickness": 15},
        [
            {"id": "plate", "type": "plate", "width": "width", "depth": "depth",
             "thickness": "thickness"},
            {"id": "pin", "type": "hole", "spec": {"kind": "plain", "diameter": 7.3},
             "depth": 8, "at": {"point": [22, "depth - 17"]}},
            {"id": "recess", "type": "pocket", "center": ["width - 30", "depth/2"],
             "size": [24, 40], "corner_radius": 0, "depth": 6},
            {"id": "guide", "type": "slot", "center": [35, 15], "length": 40, "width": 10,
             "angle": 0, "depth": 4},
        ],
    )


ALL = {"mounting_plate": mounting_plate, "bearing_bracket": bearing_bracket,
       "odd_plate": odd_plate}
