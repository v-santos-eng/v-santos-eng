"""The .cadrecipe.json format: load, validate, save, and resolve placements.

A recipe is plain JSON so it diffs well in Git and can be read by people.
See docs/format.md for the specification.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .expr import Expr, evaluate, names_in, resolve_parameters

FORMAT = "cadrecipe"
VERSION = "0.1"

FEATURE_TYPES = {"plate", "hole", "pocket", "slot"}
HOLE_KINDS = {"plain", "clearance", "tapped", "counterbore"}


class RecipeError(ValueError):
    pass


@dataclass
class Recipe:
    name: str
    parameters: dict[str, Expr]
    features: list[dict]
    units: str = "mm"
    provenance: dict = field(default_factory=dict)

    # ---- (de)serialisation -------------------------------------------------

    @classmethod
    def from_dict(cls, data: dict) -> Recipe:
        if data.get("format") != FORMAT:
            raise RecipeError("not a cadrecipe document (missing format tag)")
        if str(data.get("version")) != VERSION:
            raise RecipeError(f"unsupported cadrecipe version {data.get('version')}")
        recipe = cls(
            name=data.get("name", "part"),
            parameters=dict(data.get("parameters", {})),
            features=list(data.get("features", [])),
            units=data.get("units", "mm"),
            provenance=dict(data.get("provenance", {})),
        )
        recipe.validate()
        return recipe

    @classmethod
    def load(cls, path: str | Path) -> Recipe:
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def to_dict(self) -> dict:
        out = {
            "format": FORMAT,
            "version": VERSION,
            "name": self.name,
            "units": self.units,
            "parameters": self.parameters,
            "features": self.features,
        }
        if self.provenance:
            out["provenance"] = self.provenance
        return out

    def save(self, path: str | Path) -> None:
        Path(path).write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    # ---- semantics -----------------------------------------------------------

    def env(self, overrides: dict[str, Expr] | None = None) -> dict[str, float]:
        params = dict(self.parameters)
        if overrides:
            unknown = set(overrides) - set(params)
            if unknown:
                raise RecipeError(f"unknown parameters: {sorted(unknown)}")
            params.update(overrides)
        return resolve_parameters(params)

    @property
    def plate(self) -> dict:
        return self.features[0]

    def validate(self) -> None:
        if self.units != "mm":
            raise RecipeError("only mm is supported in v0.1")
        if not self.features or self.features[0].get("type") != "plate":
            raise RecipeError("the first feature must be the plate")
        ids = set()
        for i, feat in enumerate(self.features):
            ftype = feat.get("type")
            if ftype not in FEATURE_TYPES:
                raise RecipeError(f"feature {i}: unknown type {ftype!r}")
            if ftype == "plate" and i > 0:
                raise RecipeError(f"feature {i}: only one plate is allowed")
            fid = feat.get("id")
            if fid:
                if fid in ids:
                    raise RecipeError(f"duplicate feature id {fid!r}")
                ids.add(fid)
            if ftype == "hole":
                kind = feat.get("spec", {}).get("kind")
                if kind not in HOLE_KINDS:
                    raise RecipeError(f"feature {i}: unknown hole kind {kind!r}")
                if "at" not in feat:
                    raise RecipeError(f"feature {i}: hole needs a placement 'at'")
        # every name used anywhere must be a parameter, and values must resolve
        known = set(self.parameters)
        for i, feat in enumerate(self.features):
            for e in _expressions(feat):
                missing = names_in(e) - known
                if missing:
                    raise RecipeError(
                        f"feature {i}: unknown parameters {sorted(missing)} in {e!r}"
                    )
        self.env()


def _expressions(obj) -> list[Expr]:
    """All expression leaves inside a feature (skips names and enums)."""
    skip = {"type", "id", "kind", "size", "fit", "evidence", "alternatives", "depth"}
    out: list[Expr] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "depth" and v != "through":
                out.append(v)
            elif k not in skip:
                out.extend(_expressions(v))
    elif isinstance(obj, list):
        for v in obj:
            out.extend(_expressions(v))
    elif isinstance(obj, (str, int, float)) and not isinstance(obj, bool):
        out.append(obj)
    return out


# ---- placements ---------------------------------------------------------------


def placement_exprs(at: dict, env: dict[str, float]) -> list[tuple[str, str]]:
    """Hole centres as (x, y) expression strings, keeping the parametric link.

    Counts are evaluated (a CAD sketch needs a fixed number of points); every
    coordinate stays an expression of the recipe parameters.
    """
    if "point" in at:
        x, y = at["point"]
        return [(str(x), str(y))]
    if "grid" in at:
        g = at["grid"]
        (ox, oy), (nx, ny), (px, py) = g["origin"], g["count"], g["pitch"]
        nx_i, ny_i = _count(nx, env), _count(ny, env)
        pts = []
        for j in range(ny_i):
            for i in range(nx_i):
                pts.append((_offset(ox, i, px), _offset(oy, j, py)))
        return pts
    if "circle" in at:
        c = at["circle"]
        (cx, cy), r, n = c["center"], c["radius"], c["count"]
        start = c.get("start_angle", 0)
        n_i = _count(n, env)
        pts = []
        for i in range(n_i):
            ang = f"({start}) + {i}*360/({n})" if i else f"({start})"
            pts.append(
                (f"({cx}) + ({r})*cos({ang})", f"({cy}) + ({r})*sin({ang})")
            )
        return pts
    raise RecipeError(f"unknown placement: {sorted(at)}")


def placement_points(at: dict, env: dict[str, float]) -> list[tuple[float, float]]:
    return [(evaluate(x, env), evaluate(y, env)) for x, y in placement_exprs(at, env)]


def _offset(origin: Expr, i: int, pitch: Expr) -> str:
    if i == 0:
        return str(origin)
    if i == 1:
        return f"({origin}) + ({pitch})"
    return f"({origin}) + {i}*({pitch})"


def _count(expr: Expr, env: dict[str, float]) -> int:
    v = evaluate(expr, env)
    if v < 1 or abs(v - round(v)) > 1e-9:
        raise RecipeError(f"pattern count must be a positive integer, got {v}")
    return int(round(v))
