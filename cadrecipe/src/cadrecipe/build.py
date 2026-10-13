"""Reference builder: recipe -> B-rep solid with OpenCascade (build123d).

This is the ground truth the CAD writers are checked against. Conventions:
the plate occupies x in [0, width], y in [0, depth], z in [0, thickness];
holes, pockets and slots are machined from the top face (z = thickness).
"""

from __future__ import annotations

from pathlib import Path

from build123d import (
    Align,
    Axis,
    Box,
    Cylinder,
    Part,
    Pos,
    Rectangle,
    RectangleRounded,
    Rot,
    SlotOverall,
    chamfer,
    export_step,
    extrude,
    fillet,
)

from .expr import evaluate
from .recipe import Recipe, RecipeError, placement_points
from .standards import hole_geometry

_OVER = 1.0  # tool overshoot past faces, avoids coplanar booleans


def build(recipe: Recipe, overrides: dict | None = None) -> Part:
    env = recipe.env(overrides)
    plate = recipe.plate
    w, d, t = (evaluate(plate[k], env) for k in ("width", "depth", "thickness"))
    part = Box(w, d, t, align=(Align.MIN, Align.MIN, Align.MIN))
    corners = plate.get("corners")
    if corners:
        size = evaluate(corners["size"], env)
        edges = part.edges().filter_by(Axis.Z)
        if corners["type"] == "fillet":
            part = fillet(edges, radius=size)
        elif corners["type"] == "chamfer":
            part = chamfer(edges, length=size)
        else:
            raise RecipeError(f"unknown corner type {corners['type']!r}")

    tools = []
    for feat in recipe.features[1:]:
        tools.extend(_tools(feat, env, t))
    if tools:
        part = part.cut(*tools)
    return part


def _depth(feat: dict, env: dict, t: float) -> float:
    depth = feat.get("depth", "through")
    return t + _OVER if depth == "through" else evaluate(depth, env)


def _tools(feat: dict, env: dict, t: float) -> list:
    ftype = feat["type"]
    if ftype == "hole":
        geo = hole_geometry(feat["spec"], env)
        depth = _depth(feat, env, t)
        out = []
        for x, y in placement_points(feat["at"], env):
            out.append(_cyl(x, y, t, geo.diameter, depth))
            if geo.cbore_diameter:
                out.append(_cyl(x, y, t, geo.cbore_diameter, geo.cbore_depth))
        return out
    if ftype in ("pocket", "slot"):
        cx, cy = (evaluate(v, env) for v in feat["center"])
        angle = evaluate(feat.get("angle", 0), env)
        depth = _depth(feat, env, t)
        if ftype == "pocket":
            length, width = (evaluate(v, env) for v in feat["size"])
            r = evaluate(feat.get("corner_radius", 0), env)
            sketch = RectangleRounded(length, width, r) if r > 0 else Rectangle(length, width)
        else:
            sketch = SlotOverall(evaluate(feat["length"], env), evaluate(feat["width"], env))
        placed = Pos(cx, cy, t + _OVER) * Rot(0, 0, angle) * sketch
        return [extrude(placed, amount=-(depth + _OVER))]
    raise RecipeError(f"cannot build feature type {ftype!r}")


def _cyl(x: float, y: float, top: float, dia: float, depth: float):
    height = depth + _OVER
    return Pos(x, y, top + _OVER) * Cylinder(
        dia / 2, height, align=(Align.CENTER, Align.CENTER, Align.MAX)
    )


def build_step(recipe: Recipe, path: str | Path, overrides: dict | None = None) -> Part:
    part = build(recipe, overrides)
    export_step(part, str(path))
    return part
