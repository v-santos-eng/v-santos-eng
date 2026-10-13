"""STEP -> recipe: recover features and design intent from a dead solid.

Method ("removed-volume decomposition"):

1. Normalise the solid so the plate lies on XY with its thinnest extent on Z
   and machined features opening upwards.
2. Subtract the part from its bounding stock. Every connected piece of the
   removed volume is one machining operation: a hole, a counterbore, a
   pocket, a slot, or the material taken off a plate corner.
3. Classify each piece from its faces (planes and vertical cylinders).
4. Infer intent across pieces: standard hole sizes, grids and bolt circles,
   symmetry about the plate centre, positions referenced to the nearest edge.

Every inference carries its evidence. Anything not understood is listed in
provenance["unrecognized"] instead of being guessed, and verify() will show
the leftover volume.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from build123d import Align, Box, GeomType, Location, Solid, import_step

from .expr import fmt
from .recipe import Recipe
from .standards import match_counterbore, match_simple_hole

TOL = 1e-3  # mm, geometric comparison tolerance


# ---- normalisation -------------------------------------------------------------


def load_solid(path: str | Path) -> Solid:
    shape = import_step(str(path))
    solids = shape.solids()
    if len(solids) != 1:
        raise ValueError(f"expected one solid in {path}, found {len(solids)}")
    return solids[0]


def normalize(solid: Solid, flip: bool = False) -> tuple[Solid, dict]:
    """Thinnest extent on Z, bounding box min corner at the origin."""
    bb = solid.bounding_box()
    size = (bb.size.X, bb.size.Y, bb.size.Z)
    thin = min(range(3), key=lambda i: size[i])
    rotation = {0: (0, -90, 0), 1: (90, 0, 0), 2: (0, 0, 0)}[thin]
    if flip:
        rotation = (rotation[0] + 180, rotation[1], rotation[2])
    out = solid.moved(Location((0, 0, 0), rotation))
    bb = out.bounding_box()
    out = out.moved(Location((-bb.min.X, -bb.min.Y, -bb.min.Z)))
    return out, {"rotation_deg": list(rotation), "flipped": flip}


# ---- pieces of removed volume ----------------------------------------------------


@dataclass
class Piece:
    kind: str  # corner | hole | pocket | slot | unknown
    data: dict
    top_open: bool
    bottom_open: bool


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= TOL


def _cylinders(piece: Solid) -> list[dict]:
    out = []
    for f in piece.faces():
        if f.geom_type != GeomType.CYLINDER:
            continue
        axis = f.axis_of_rotation
        fb = f.bounding_box()
        out.append(
            {
                "r": f.radius,
                "vertical": abs(abs(axis.direction.Z) - 1) <= 1e-6,
                "x": axis.position.X,
                "y": axis.position.Y,
                "zmin": fb.min.Z,
                "zmax": fb.max.Z,
            }
        )
    return out


def _distinct(values: list[float]) -> list[float]:
    out: list[float] = []
    for v in sorted(values):
        if not out or not _close(v, out[-1]):
            out.append(v)
    return out


def _classify(piece: Solid, W: float, D: float, T: float) -> Piece:
    bb = piece.bounding_box()
    top_open = _close(bb.max.Z, T)
    bottom_open = _close(bb.min.Z, 0)
    faces = piece.faces()
    types = {f.geom_type for f in faces}
    cyls = _cylinders(piece)
    info = {"bbox": [[round(bb.min.X, 3), round(bb.min.Y, 3), round(bb.min.Z, 3)],
                     [round(bb.max.X, 3), round(bb.max.Y, 3), round(bb.max.Z, 3)]]}

    def unknown(reason: str) -> Piece:
        return Piece("unknown", {**info, "reason": reason,
                                 "face_types": sorted(t.name for t in types)},
                     top_open, bottom_open)

    if not types <= {GeomType.PLANE, GeomType.CYLINDER}:
        return unknown("faces other than planes and cylinders")
    if any(not c["vertical"] for c in cyls):
        return unknown("cylinder not perpendicular to the plate")
    planes_ok = all(
        f.geom_type != GeomType.PLANE
        or abs(abs(f.normal_at().Z) - 1) <= 1e-6
        or abs(f.normal_at().Z) <= 1e-6
        for f in faces
    )
    on_x = _close(bb.min.X, 0) or _close(bb.max.X, W)
    on_y = _close(bb.min.Y, 0) or _close(bb.max.Y, D)

    # material removed at a plate corner (full height, touching two sides)
    if on_x and on_y and top_open and bottom_open:
        if len(cyls) and len(_distinct([c["r"] for c in cyls])) == 1:
            return Piece("corner", {"type": "fillet", "size": cyls[0]["r"]}, True, True)
        if not cyls and _close(bb.size.X, bb.size.Y):
            return Piece("corner", {"type": "chamfer", "size": bb.size.X}, True, True)
        return unknown("corner material that is neither a fillet nor an equal chamfer")
    if on_x or on_y:
        return unknown("feature breaks through the plate outline")
    if not planes_ok:
        return unknown("inclined planar face")

    open_z = bb.max.Z if top_open else bb.min.Z
    depth = T if (top_open and bottom_open) else abs(open_z - (bb.min.Z if top_open else bb.max.Z))
    through = top_open and bottom_open
    axes = {(round(c["x"], 3), round(c["y"], 3)) for c in cyls}
    vertical_planes = [
        f for f in faces
        if f.geom_type == GeomType.PLANE and abs(f.normal_at().Z) <= 1e-6
    ]

    # hole: only coaxial cylinders and horizontal planes
    if cyls and len(axes) == 1 and not vertical_planes:
        radii = _distinct([c["r"] for c in cyls])
        (x, y), = axes
        if len(radii) == 1:
            return Piece("hole", {"x": x, "y": y, "d": 2 * radii[0],
                                  "depth": None if through else depth}, top_open, bottom_open)
        if len(radii) == 2:
            small, big = radii
            big_faces = [c for c in cyls if _close(c["r"], big)]
            big_z0 = min(c["zmin"] for c in big_faces)
            big_z1 = max(c["zmax"] for c in big_faces)
            cb_depth = big_z1 - big_z0
            mouth_up = top_open and _close(big_z1, T)
            mouth_down = bottom_open and _close(big_z0, 0)
            if mouth_up or mouth_down:
                # a counterbore faces one way even when its hole goes through,
                # so report only the mouth side (this drives the flip vote)
                return Piece("hole", {"x": x, "y": y, "d": 2 * small, "cbore_d": 2 * big,
                                      "cbore_depth": cb_depth,
                                      "depth": None if through else depth},
                             mouth_up, mouth_down)
        return unknown("coaxial cylinders that are not a simple or counterbored hole")

    # pocket / slot: vertical walls, rounded corners, flat floor
    cx, cy = (bb.min.X + bb.max.X) / 2, (bb.min.Y + bb.max.Y) / 2
    lx, ly = bb.size.X, bb.size.Y
    data = {"cx": cx, "cy": cy, "depth": None if through else depth}
    radii = _distinct([c["r"] for c in cyls])
    if not cyls and len(vertical_planes) == 4:
        return Piece("pocket", {**data, "lx": lx, "ly": ly, "r": 0.0}, top_open, bottom_open)
    if len(radii) == 1:
        r = radii[0]
        if len(axes) == 2 and _close(2 * r, min(lx, ly)):
            return Piece("slot", {**data, "length": max(lx, ly), "width": 2 * r,
                                  "angle": 0 if lx >= ly else 90}, top_open, bottom_open)
        if len(axes) == 4:
            return Piece("pocket", {**data, "lx": lx, "ly": ly, "r": r}, top_open, bottom_open)
    return unknown("closed outline that is not an axis-aligned pocket or slot")


def _decompose(solid: Solid, W: float, D: float, T: float) -> list[Piece]:
    stock = Box(W, D, T, align=(Align.MIN, Align.MIN, Align.MIN))
    removed = stock.cut(solid)
    pieces = [p for p in removed.solids() if p.volume > 1e-6]
    return [_classify(p, W, D, T) for p in pieces]


# ---- intent inference ------------------------------------------------------------


def _pos(v: float, extent_name: str, extent: float) -> str:
    """Express a coordinate the way a designer would dimension it."""
    if _close(v, extent / 2):
        return f"{extent_name}/2"
    if v <= extent / 2:
        return fmt(v)
    return f"{extent_name} - {fmt(extent - v)}"


def _equal_steps(vals: list[float]) -> float | None:
    if len(vals) < 2:
        return 0.0
    steps = [b - a for a, b in zip(vals, vals[1:])]
    return steps[0] if all(_close(s, steps[0]) for s in steps) else None


class _Names:
    def __init__(self):
        self.used: set[str] = set()

    def take(self, base: str) -> str:
        base = re.sub(r"[^a-z0-9_]", "_", base.lower())
        name, n = base, 2
        while name in self.used:
            name, n = f"{base}_{n}", n + 1
        self.used.add(name)
        return name


def _spec_label(spec: dict) -> str:
    if spec["kind"] == "plain" or "size" not in spec:
        return f"hole_{spec.get('diameter', 'd').replace('.', '_')}"
    return f"{spec['size']}_{spec['kind']}".lower()


def _grid(pts, W, D, names: _Names, label: str, params: dict) -> tuple[dict, str] | None:
    xs, ys = _distinct([p[0] for p in pts]), _distinct([p[1] for p in pts])
    if len(xs) * len(ys) != len(pts) or len(pts) < 2:
        return None
    present = {(round(x, 3), round(y, 3)) for x, y in pts}
    if any((round(x, 3), round(y, 3)) not in present for x in xs for y in ys):
        return None
    px, py = _equal_steps(xs), _equal_steps(ys)
    if px is None or py is None:
        return None

    sym_x = len(xs) > 1 and _close(xs[0], W - xs[-1])
    sym_y = len(ys) > 1 and _close(ys[0], D - ys[-1])
    origin, pitch, notes = ["", ""], ["0", "0"], []
    shared = sym_x and sym_y and _close(xs[0], ys[0])
    if shared:
        m = names.take(f"{label}_margin")
        params[m] = fmt(xs[0])
    for axis, vals, step, sym, ext_name, ext in (
        (0, xs, px, sym_x, "width", W),
        (1, ys, py, sym_y, "depth", D),
    ):
        letter = "xy"[axis]
        if len(vals) == 1:
            origin[axis] = _pos(vals[0], ext_name, ext)
            continue
        if sym:
            m = f"{label}_margin" if shared else names.take(f"{label}_margin_{letter}")
            if not shared:
                params[m] = fmt(vals[0])
            p = names.take(f"{label}_pitch_{letter}")
            n1 = len(vals) - 1
            params[p] = f"({ext_name} - 2*{m}) / {n1}" if n1 > 1 else f"{ext_name} - 2*{m}"
            origin[axis], pitch[axis] = m, p
            notes.append(f"symmetric in {letter} (margin {fmt(vals[0])} each side)")
        else:
            p = names.take(f"{label}_pitch_{letter}")
            params[p] = fmt(step)
            origin[axis], pitch[axis] = _pos(vals[0], ext_name, ext), p
    at = {"grid": {"origin": origin, "count": [len(xs), len(ys)], "pitch": pitch}}
    ev = f"{len(pts)} holes on a {len(xs)}x{len(ys)} grid, pitch {fmt(px)} x {fmt(py)}"
    if notes:
        ev += "; " + "; ".join(notes)
    return at, ev


def _circle(pts, W, D, names: _Names, label: str, params: dict) -> tuple[dict, str] | None:
    n = len(pts)
    if n < 3:
        return None
    cx = sum(p[0] for p in pts) / n
    cy = sum(p[1] for p in pts) / n
    radii = [math.hypot(x - cx, y - cy) for x, y in pts]
    r = radii[0]
    if r < TOL or any(not _close(ri, r) for ri in radii):
        return None
    angles = sorted(math.degrees(math.atan2(y - cy, x - cx)) % 360 for x, y in pts)
    step = 360 / n
    gaps = [b - a for a, b in zip(angles, angles[1:])] + [angles[0] + 360 - angles[-1]]
    if any(abs(g - step) > 0.01 for g in gaps):
        return None
    start = angles[0] % step
    rname = names.take(f"{label}_circle_r")
    params[rname] = fmt(r)
    at = {"circle": {"center": [_pos(cx, "width", W), _pos(cy, "depth", D)],
                     "radius": rname, "count": n, "start_angle": fmt(start, 2)}}
    ev = f"{n} holes equally spaced on Ø{fmt(2 * float(fmt(r)))} circle, start {fmt(start, 2)}°"
    return at, ev


def _ugliness(params: dict, at: dict) -> int:
    """How many literal dimensions are not multiples of 0.5 mm (or 0.5°).
    Designers dimension in round numbers, so the reading of a hole pattern
    that needs fewer odd literals is the one closest to the original intent."""
    literals = [v for v in params.values()]
    for key in ("grid", "circle"):
        if key in at:
            body = at[key]
            literals += list(body.get("origin", [])) + list(body.get("center", []))
            literals.append(body.get("start_angle", 0))
    score = 0
    for v in literals:
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue  # an expression, not a literal
        score += abs(f * 2 - round(f * 2)) > 1e-6
    return score


def _best_pattern(pts, W, D, names: _Names, label: str, params: dict):
    candidates = []
    for finder in (_grid, _circle):
        trial_names, trial_params = _Names(), {}
        trial_names.used = set(names.used)
        found = finder(pts, W, D, trial_names, label, trial_params)
        if found:
            candidates.append((_ugliness(trial_params, found[0]), len(candidates),
                               found, trial_names, trial_params))
    if not candidates:
        return None
    _, _, found, best_names, best_params = min(candidates, key=lambda c: c[:2])
    names.used = best_names.used
    params.update(best_params)
    return found


def _hole_spec(p: dict) -> tuple[dict, str, tuple]:
    if "cbore_d" in p:
        m = match_counterbore(p["d"], p["cbore_d"], p["cbore_depth"])
        if m:
            return m.spec, m.evidence, m.alternatives
        spec = {"kind": "counterbore", "diameter": fmt(p["d"]),
                "cbore_diameter": fmt(p["cbore_d"]), "cbore_depth": fmt(p["cbore_depth"])}
        return spec, "counterbore with non-standard sizes; kept as measured", ()
    m = match_simple_hole(p["d"])
    return m.spec, m.evidence, m.alternatives


# ---- entry points ----------------------------------------------------------------


def recognize_solid(solid: Solid, name: str = "part") -> tuple[Recipe, Solid]:
    norm, transform = normalize(solid)
    bb = norm.bounding_box()
    W, D, T = bb.size.X, bb.size.Y, bb.size.Z
    pieces = _decompose(norm, W, D, T)
    # features opening only on the underside: turn the part over and retry
    blind_up = sum(p.top_open and not p.bottom_open for p in pieces)
    blind_down = sum(p.bottom_open and not p.top_open for p in pieces)
    if blind_down > blind_up:
        norm, transform = normalize(solid, flip=True)
        pieces = _decompose(norm, W, D, T)

    names = _Names()
    for reserved in ("width", "depth", "thickness"):
        names.take(reserved)
    params: dict = {"width": fmt(W), "depth": fmt(D), "thickness": fmt(T)}
    plate = {"id": "plate", "type": "plate", "width": "width", "depth": "depth",
             "thickness": "thickness"}
    features: list[dict] = [plate]
    unrecognized: list[dict] = []

    corners = [p for p in pieces if p.kind == "corner"]
    if corners:
        kinds = {(c.data["type"], round(c.data["size"], 3)) for c in corners}
        if len(corners) == 4 and len(kinds) == 1:
            ctype, size = kinds.pop()
            cname = names.take("corner_r" if ctype == "fillet" else "corner_chamfer")
            params[cname] = fmt(size)
            plate["corners"] = {"type": ctype, "size": cname}
            plate["evidence"] = f"4 equal corner {ctype}s of {fmt(size)} mm"
        else:
            unrecognized.extend({"reason": "corners differ", **c.data} for c in corners)

    groups: dict = defaultdict(list)
    for p in pieces:
        if p.kind == "unknown" or (p.kind != "corner" and not p.top_open):
            unrecognized.append(p.data if p.kind == "unknown"
                                else {"reason": "opens on the underside", **p.data})
        elif p.kind == "hole":
            spec, ev, alts = _hole_spec(p.data)
            depth = "through" if p.data["depth"] is None else fmt(p.data["depth"])
            key = (repr(sorted(spec.items())), depth)
            groups[key].append((p.data["x"], p.data["y"], spec, ev, alts, depth))

    for members in groups.values():
        pts = [(m[0], m[1]) for m in members]
        spec, ev, alts, depth = members[0][2], members[0][3], members[0][4], members[0][5]
        label = _spec_label(spec)
        found = _best_pattern(pts, W, D, names, label, params)
        placements = [found] if found else [
            ({"point": [_pos(x, "width", W), _pos(y, "depth", D)]}, "single hole")
            for x, y in sorted(pts)
        ]
        for at, pattern_ev in placements:
            feat = {"id": names.take(label), "type": "hole", "spec": spec,
                    "depth": depth, "at": at, "evidence": f"{ev}; {pattern_ev}"}
            if alts:
                feat["alternatives"] = list(alts)
            features.append(feat)

    for p in pieces:
        if p.kind not in ("pocket", "slot") or not p.top_open:
            continue
        d = p.data
        center = [_pos(d["cx"], "width", W), _pos(d["cy"], "depth", D)]
        depth = "through" if d["depth"] is None else fmt(d["depth"])
        if p.kind == "pocket":
            feat = {"id": names.take("pocket"), "type": "pocket", "center": center,
                    "size": [fmt(d["lx"]), fmt(d["ly"])], "corner_radius": fmt(d["r"]),
                    "depth": depth,
                    "evidence": f"{fmt(d['lx'])} x {fmt(d['ly'])} pocket, corner R{fmt(d['r'])}"}
        else:
            feat = {"id": names.take("slot"), "type": "slot", "center": center,
                    "length": fmt(d["length"]), "width": fmt(d["width"]),
                    "angle": d["angle"], "depth": depth,
                    "evidence": f"slot {fmt(d['length'])} x {fmt(d['width'])} overall"}
        features.append(feat)

    provenance = {"recognizer": "cadrecipe 0.1", "normalization": transform}
    if unrecognized:
        provenance["unrecognized"] = unrecognized
    return Recipe(name, _numeric(params), _numeric_tree(features), provenance=provenance), norm


def recognize(path: str | Path) -> tuple[Recipe, Solid]:
    path = Path(path)
    recipe, norm = recognize_solid(load_solid(path), name=path.stem)
    recipe.provenance["source"] = path.name
    return recipe, norm


def _number(v):
    if isinstance(v, str):
        try:
            f = float(v)
        except ValueError:
            return v
        return int(f) if f.is_integer() else f
    return v


def _numeric(params: dict) -> dict:
    """Plain numbers as JSON numbers, relations as expression strings."""
    return {k: _number(v) for k, v in params.items()}


def _numeric_tree(obj, key: str = ""):
    if isinstance(obj, dict):
        return {k: _numeric_tree(v, k) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_numeric_tree(v, key) for v in obj]
    return obj if key in ("id", "evidence", "alternatives") else _number(obj)
