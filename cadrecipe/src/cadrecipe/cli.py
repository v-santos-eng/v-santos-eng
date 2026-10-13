"""Command line: cadrecipe recognize | build | verify | inventor"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .recipe import Recipe


def _overrides(pairs: list[str]) -> dict:
    out = {}
    for pair in pairs:
        name, _, value = pair.partition("=")
        if not value:
            raise SystemExit(f"--set expects name=value, got {pair!r}")
        out[name.strip()] = value.strip()
    return out


def cmd_recognize(args) -> int:
    from .recognize import recognize
    from .verify import verify

    recipe, normalized = recognize(args.step)
    out = Path(args.output or Path(args.step).with_suffix(".cadrecipe.json"))
    recipe.save(out)
    print(f"recipe written to {out}\n")
    for feat in recipe.features:
        print(f"  {feat['id']:<22} {feat.get('evidence', '')}")
        for alt in feat.get("alternatives", []):
            print(f"  {'':<22}   also possible: {alt}")
    unknown = recipe.provenance.get("unrecognized", [])
    for item in unknown:
        print(f"  NOT RECOGNISED         {item.get('reason')} at {item.get('bbox')}")
    result = verify(recipe, normalized)
    print(f"\n{result.summary()}")
    return 0 if result.ok else 1


def cmd_build(args) -> int:
    from .build import build_step

    recipe = Recipe.load(args.recipe)
    part = build_step(recipe, args.output, _overrides(args.set))
    print(f"{args.output}: volume {part.volume:.3f} mm³")
    return 0


def cmd_verify(args) -> int:
    from .recognize import load_solid, normalize
    from .verify import verify

    recipe = Recipe.load(args.recipe)
    flip = recipe.provenance.get("normalization", {}).get("flipped", False)
    normalized, _ = normalize(load_solid(args.step), flip=flip)
    result = verify(recipe, normalized)
    print(result.summary())
    return 0 if result.ok else 1


def cmd_inventor(args) -> int:
    from .writers.inventor import write_script

    recipe = Recipe.load(args.recipe)
    out = write_script(recipe, args.output or f"{recipe.name}_inventor.py")
    print(f"Inventor script written to {out}. Run it on Windows with Inventor open.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cadrecipe", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("recognize", help="STEP -> recipe, with evidence and verification")
    p.add_argument("step")
    p.add_argument("-o", "--output")
    p.set_defaults(func=cmd_recognize)

    p = sub.add_parser("build", help="recipe -> STEP (reference kernel)")
    p.add_argument("recipe")
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--set", action="append", default=[], metavar="NAME=EXPR",
                   help="override a parameter, e.g. --set width=300")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("verify", help="check that a recipe rebuilds a STEP exactly")
    p.add_argument("recipe")
    p.add_argument("step")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("inventor", help="recipe -> Python script that models it in Inventor")
    p.add_argument("recipe")
    p.add_argument("-o", "--output")
    p.set_defaults(func=cmd_inventor)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
