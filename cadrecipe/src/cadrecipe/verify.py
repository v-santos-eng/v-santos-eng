"""Geometric check: does a recipe rebuild the original solid?"""

from __future__ import annotations

from dataclasses import dataclass

from build123d import Solid

from .build import build
from .recipe import Recipe

REL_TOL = 1e-6


@dataclass
class Verification:
    original_volume: float
    rebuilt_volume: float
    missing_volume: float  # in the original, absent from the rebuild
    extra_volume: float  # in the rebuild, absent from the original

    @property
    def deviation(self) -> float:
        return (self.missing_volume + self.extra_volume) / self.original_volume

    @property
    def ok(self) -> bool:
        return self.deviation <= REL_TOL

    def summary(self) -> str:
        status = "MATCH" if self.ok else "MISMATCH"
        return (
            f"{status}: original {self.original_volume:.3f} mm³, rebuilt "
            f"{self.rebuilt_volume:.3f} mm³, missing {self.missing_volume:.3f}, "
            f"extra {self.extra_volume:.3f} (relative deviation {self.deviation:.2e})"
        )


def compare(original: Solid, rebuilt) -> Verification:
    missing = original.cut(rebuilt).volume
    extra = rebuilt.cut(original).volume
    return Verification(original.volume, rebuilt.volume, missing, extra)


def verify(recipe: Recipe, normalized_original: Solid) -> Verification:
    return compare(normalized_original, build(recipe))
