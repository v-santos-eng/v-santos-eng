# The cadrecipe format, version 0.1

A `.cadrecipe.json` file describes a part as a designer would explain it: named
dimensions, the relations between them, and machining features with their
standard meaning ("clearance hole for M8"), instead of faces and edges. The
geometry is derived from the recipe, never stored in it.

Version 0.1 covers prismatic plates: a rectangular blank with features
machined from the top face. That is a small slice of mechanical parts, but it
includes most of the brackets, adapter plates and mounting plates of a
machine.

## Document

```json
{
  "format": "cadrecipe",
  "version": "0.1",
  "name": "mounting_plate",
  "units": "mm",
  "parameters": { ... },
  "features": [ ... ],
  "provenance": { ... }
}
```

`units` must be `mm`. `provenance` is optional and written by tools (source
file, normalisation applied, anything the recogniser did not understand). It
never affects geometry.

## Parameters

A map from name to a number or an expression string:

```json
"parameters": {
  "width": 200,
  "margin": 20,
  "pitch_x": "(width - 2*margin) / 2"
}
```

Expressions may use `+ - * / ** %`, parentheses, other parameters, and
`abs min max round sqrt sin cos tan`. Trigonometric functions take degrees.
Parameters may be listed in any order; cycles are an error.

Every dimension in a feature is also an expression, so `"width/2"` or
`"depth - 17"` are valid anywhere a number is.

## Coordinate system

The plate occupies `x ∈ [0, width]`, `y ∈ [0, depth]`, `z ∈ [0, thickness]`.
The top face is `z = thickness`. In v0.1 all features are machined from the
top face, downwards.

## Features

`features` is an ordered list. The first must be the plate. Each feature may
carry an `id`, plus `evidence` and `alternatives` (text written by the
recogniser, ignored by builders).

### plate

```json
{"type": "plate", "width": "width", "depth": "depth", "thickness": "thickness",
 "corners": {"type": "fillet", "size": "corner_r"}}
```

`corners` is optional: `fillet` (radius) or `chamfer` (equal-leg distance) on
the four vertical edges.

### hole

```json
{"type": "hole",
 "spec": {"kind": "clearance", "size": "M8", "fit": "medium"},
 "depth": "through",
 "at": {"grid": {"origin": ["margin", "margin"], "count": [3, 2],
                 "pitch": ["pitch_x", "pitch_y"]}}}
```

`spec.kind`:

| kind | fields | geometry |
| --- | --- | --- |
| `clearance` | `size` (M3 to M24), `fit` (`fine`, `medium`, `coarse`) | ISO 273 diameter |
| `tapped` | `size` | coarse-pitch tap drill; writers add the native thread |
| `counterbore` | `size` | ISO 273 medium hole + DIN 974-1 counterbore for ISO 4762 |
| `counterbore` | `diameter`, `cbore_diameter`, `cbore_depth` | non-standard counterbore |
| `plain` | `diameter` | as given |

`depth` is `"through"` or an expression (flat-bottomed blind hole).

`at` places one or more holes:

| placement | fields |
| --- | --- |
| `point` | `[x, y]` |
| `grid` | `origin [x, y]`, `count [nx, ny]`, `pitch [px, py]` (row-major from the origin) |
| `circle` | `center [x, y]`, `radius`, `count`, `start_angle` (degrees from +x) |

### pocket

```json
{"type": "pocket", "center": ["width/2", "depth/2"], "size": [30, 30],
 "corner_radius": 5, "depth": "through", "angle": 0}
```

`size` is `[length along x, width along y]` before rotation. A through pocket
is a cut-out.

### slot

```json
{"type": "slot", "center": ["width - 25", "depth/2"], "length": 30, "width": 9,
 "angle": 90, "depth": "through"}
```

`length` is the overall length, end to end. `angle` rotates about the slot
centre. Writers in v0.1 accept multiples of 90°.

## Design rules for tools

1. **Intent over coordinates.** Prefer `"width - 20"` to `180` when the
   dimension is really taken from the right-hand edge. Prefer a `grid` with a
   margin parameter to six independent points.
2. **Evidence, not guesses.** A recogniser states why it named a hole
   "M8 clearance" and lists other readings. Geometry it cannot explain goes
   to `provenance.unrecognized`, never into a made-up feature.
3. **Verify.** A recogniser's output must rebuild the source solid; a writer's
   output must match the reference build. `cadrecipe verify` measures both
   ways of the symmetric difference.
