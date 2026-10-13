# cadrecipe

Send someone a STEP file and they get a dead block: the geometry is right,
but there are no dimensions, no parameters and no real holes. If they need
the plate 100 mm wider, they model it again.

cadrecipe keeps the *recipe* of a part instead: named dimensions, the
relations between them, and features with their standard meaning. A recipe is
a small JSON file that belongs to no CAD vendor. Tools on each side translate
it:

```
            recognise                          write
STEP  ──────────────────▶  .cadrecipe.json  ──────────────▶  Inventor (native features)
(dead solid)   evidence +       (intent)                     reference kernel (STEP)
               verification                                  SolidWorks, ... (planned)
```

No CAD vendor has to adopt the format. Each writer drives its CAD system
through that system's own API and builds native features there.

## What it does today (v0.1)

Prismatic plates: rectangular blank, corner fillets or chamfers, holes,
counterbores, tapped holes, pockets and slots machined from one face.

```
$ cadrecipe recognize mounting_plate.step
  plate          4 equal corner fillets of 8 mm
  m8_clearance   Ø9 = ISO 273 medium clearance for M8; 6 holes on a 3x2 grid,
                 pitch 80 x 80; symmetric in x (margin 20 each side); symmetric in y
  m6_tapped      Ø5 = tap drill for M6x1 (STEP carries no thread; inferred from
                 drill size); 4 holes equally spaced on Ø60 circle, start 45°
  pocket         30 x 30 pocket, corner R5
  slot           slot 30 x 9 overall

MATCH: original 268401.018 mm³, rebuilt 268401.018 mm³, missing 0.000, extra 0.000
```

The recovered recipe says what a designer would have said:

```json
"parameters": {
  "width": 200, "depth": 120, "thickness": 12, "corner_r": 8,
  "m8_clearance_margin": 20,
  "m8_clearance_pitch_x": "(width - 2*m8_clearance_margin) / 2",
  "m8_clearance_pitch_y": "depth - 2*m8_clearance_margin",
  "m6_tapped_circle_r": 30
}
```

Change `width` to 300 and the M8 holes spread out keeping their 20 mm
margins, the bolt circle stays centred, and the slot stays 25 mm from the
right edge.

### How recognition works

1. Normalise: thinnest extent on Z, features opening upwards (the part is
   turned over if most features open on the underside).
2. Subtract the part from its bounding stock. Each connected piece of removed
   volume is one machining operation.
3. Classify each piece from its faces: coaxial cylinders are a hole or a
   counterbore, vertical walls with corner arcs are a pocket or a slot, full
   height material at a corner is a fillet or chamfer.
4. Infer intent: match diameters to ISO 273, tap drill and DIN 974-1 tables;
   find grids and bolt circles; detect symmetry about the plate centre;
   reference single positions to the nearest edge or the centre. When a hole
   set fits both a grid and a circle, the reading with rounder numbers wins.
5. Verify: rebuild the recipe and measure the symmetric difference with the
   original solid.

Anything it can't explain is listed under `provenance.unrecognized` and shows
up as leftover volume in the verification. It doesn't invent features.

### How it is tested

`tests/parts.py` holds synthetic parts whose design intent is known. Each one
is built, exported to STEP, recognised and then checked twice:

- **Geometry:** the recovered recipe rebuilds the STEP exactly.
- **Intent ("flex test"):** after changing a driving dimension (for example
  `width = 300`), the recovered recipe and the designer's recipe still build
  the same solid. A control test proves this check has teeth: a copy with
  holes frozen at absolute positions passes the geometry check and fails the
  flex test.

Orientation is tested too (upside down, standing on either side), along with
a part containing geometry outside the v0.1 vocabulary, which must be
reported and not guessed.

## Usage

```bash
pip install -e ".[dev]"

cadrecipe recognize part.step -o part.cadrecipe.json   # STEP -> recipe + report
cadrecipe build part.cadrecipe.json -o out.step --set width=300
cadrecipe verify part.cadrecipe.json part.step
cadrecipe inventor part.cadrecipe.json -o part_inventor.py
```

The Inventor script runs on Windows with Inventor open and `pywin32`
installed: `python part_inventor.py part.ipt`. It creates user parameters with
the recipe's expressions, a dimensioned base sketch, native Hole features
(clearance, counterbore, tapped with ISO thread info) whose centres are
dimensioned with those expressions, and the corner fillets or chamfers.

## Status and limits

- **The Inventor writer has not been run against Inventor yet.** It was
  written from the API reference, without a Windows machine. Enum values are
  read from the Inventor type library when available, with numeric fallbacks
  that should be checked (REA's .NET inspection of
  `Autodesk.Inventor.Interop.dll` can list them). Pocket and slot outlines
  are drawn at fixed size in Inventor; only their depth is parametric.
- Hole patterns become individual dimensioned points in Inventor, so pitch
  and margins are parametric but the hole count isn't.
- One face only, axis-aligned pockets and slots, flat-bottomed blind holes,
  no holes inside pockets, no features breaking through the outline.
- The reference kernel is OpenCascade (via build123d), which is also
  FreeCAD's kernel.

## Roadmap

1. Run and fix the Inventor writer on a real installation.
2. SolidWorks writer (same plan, SolidWorks API).
3. Inventor reader: export a recipe straight from an Inventor model's feature
   tree, which is exact, unlike recognition from STEP.
4. More vocabulary: features on several faces, drill points, holes in pockets,
   rotated outlines, turned parts.

## Resumo em português

O cadrecipe guarda a "receita" de uma peça (cotas nomeadas, relações entre
elas e features com significado de norma) num JSON que não pertence a nenhum
fabricante de CAD. O reconhecedor lê um STEP "morto" e deduz a receita, com
a evidência de cada conclusão e uma verificação geométrica. Os geradores
remontam a peça com features nativas em cada CAD. A v0.1 cobre placas
prismáticas. O gerador do Inventor ainda precisa ser testado numa instalação
real.

## License

MIT
