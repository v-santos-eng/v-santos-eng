"""Metric fastener hole standards used to name holes by intent.

A STEP file only says "cylinder of diameter 9". These tables let the
recogniser say "clearance hole for M8, ISO 273 medium" instead, and let the
writers ask each CAD system for its own native hole of that kind.

Values are the usual catalogue figures: ISO 273 clearance holes, ISO 261
coarse-pitch tap drills, and DIN 974-1 counterbores for ISO 4762 socket head
cap screws. Check them against your company standard before production use.
"""

from __future__ import annotations

from dataclasses import dataclass

SIZES = ["M3", "M4", "M5", "M6", "M8", "M10", "M12", "M16", "M20", "M24"]

# ISO 273 clearance hole diameters: (fine, medium, coarse)
CLEARANCE = {
    "M3": (3.2, 3.4, 3.6),
    "M4": (4.3, 4.5, 4.8),
    "M5": (5.3, 5.5, 5.8),
    "M6": (6.4, 6.6, 7.0),
    "M8": (8.4, 9.0, 10.0),
    "M10": (10.5, 11.0, 12.0),
    "M12": (13.0, 13.5, 14.5),
    "M16": (17.0, 17.5, 18.5),
    "M20": (21.0, 22.0, 24.0),
    "M24": (25.0, 26.0, 28.0),
}
FITS = ("fine", "medium", "coarse")

# Coarse thread pitch and tap drill diameter
THREAD = {
    "M3": (0.5, 2.5),
    "M4": (0.7, 3.3),
    "M5": (0.8, 4.2),
    "M6": (1.0, 5.0),
    "M8": (1.25, 6.8),
    "M10": (1.5, 8.5),
    "M12": (1.75, 10.2),
    "M16": (2.0, 14.0),
    "M20": (2.5, 17.5),
    "M24": (3.0, 21.0),
}

# DIN 974-1 counterbore for ISO 4762: (counterbore diameter, depth).
# The through hole under it is the ISO 273 medium clearance.
COUNTERBORE = {
    "M3": (6.5, 3.4),
    "M4": (8.0, 4.4),
    "M5": (10.0, 5.4),
    "M6": (11.0, 6.4),
    "M8": (15.0, 8.6),
    "M10": (18.0, 10.6),
    "M12": (20.0, 12.6),
    "M16": (26.0, 16.6),
    "M20": (33.0, 20.6),
    "M24": (40.0, 24.8),
}


@dataclass(frozen=True)
class HoleGeometry:
    """What a hole spec turns into physically."""

    diameter: float
    cbore_diameter: float | None = None
    cbore_depth: float | None = None


def hole_geometry(spec: dict, env: dict | None = None) -> HoleGeometry:
    from .expr import evaluate

    kind = spec["kind"]
    env = env or {}
    if kind == "plain":
        return HoleGeometry(evaluate(spec["diameter"], env))
    if kind == "counterbore" and "size" not in spec:
        return HoleGeometry(
            evaluate(spec["diameter"], env),
            evaluate(spec["cbore_diameter"], env),
            evaluate(spec["cbore_depth"], env),
        )
    size = spec["size"]
    if size not in SIZES:
        raise ValueError(f"unsupported thread size: {size}")
    if kind == "clearance":
        fit = spec.get("fit", "medium")
        return HoleGeometry(CLEARANCE[size][FITS.index(fit)])
    if kind == "tapped":
        return HoleGeometry(THREAD[size][1])
    if kind == "counterbore":
        cd, depth = COUNTERBORE[size]
        return HoleGeometry(CLEARANCE[size][1], cd, depth)
    raise ValueError(f"unknown hole kind: {kind}")


@dataclass(frozen=True)
class SpecMatch:
    spec: dict
    evidence: str
    alternatives: tuple[str, ...] = ()


def match_simple_hole(diameter: float, tol: float = 0.01) -> SpecMatch:
    """Name a single-diameter hole. Clearance wins over tapped when a
    diameter fits both (e.g. 17.5 is M16 medium clearance and M20 tap drill),
    and the alternative is reported so a human can overrule it."""
    candidates: list[tuple[dict, str]] = []
    for size in SIZES:
        for fit, d in zip(FITS, CLEARANCE[size]):
            if abs(d - diameter) <= tol:
                candidates.append(
                    (
                        {"kind": "clearance", "size": size, "fit": fit},
                        f"Ø{diameter:g} = ISO 273 {fit} clearance for {size}",
                    )
                )
    for size in SIZES:
        if abs(THREAD[size][1] - diameter) <= tol:
            candidates.append(
                (
                    {"kind": "tapped", "size": size},
                    f"Ø{diameter:g} = tap drill for {size}x{THREAD[size][0]:g}"
                    " (STEP carries no thread; inferred from drill size)",
                )
            )
    if not candidates:
        from .expr import fmt

        return SpecMatch(
            {"kind": "plain", "diameter": fmt(diameter)},
            f"Ø{diameter:g} matches no metric standard hole; kept as plain",
        )
    spec, evidence = candidates[0]
    others = tuple(e for _, e in candidates[1:])
    return SpecMatch(spec, evidence, others)


def match_counterbore(
    hole_d: float, cbore_d: float, cbore_depth: float, tol: float = 0.01
) -> SpecMatch | None:
    for size in SIZES:
        cd, depth = COUNTERBORE[size]
        if (
            abs(CLEARANCE[size][1] - hole_d) <= tol
            and abs(cd - cbore_d) <= tol
            and abs(depth - cbore_depth) <= tol
        ):
            return SpecMatch(
                {"kind": "counterbore", "size": size},
                f"Ø{hole_d:g} / Ø{cbore_d:g}x{cbore_depth:g} = DIN 974-1"
                f" counterbore for ISO 4762 {size}",
            )
    return None
