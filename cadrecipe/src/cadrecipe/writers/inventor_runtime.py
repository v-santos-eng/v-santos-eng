# cadrecipe -> Autodesk Inventor runtime.
#
# This file is copied verbatim into every generated script, followed by the
# PLAN for one part. It needs Windows, Inventor and pywin32 (pip install
# pywin32). Run the generated script with Inventor open:
#
#     python mounting_plate_inventor.py [output.ipt]
#
# UNTESTED AGAINST A LIVE INVENTOR. The calls follow the Inventor API
# reference, but they have not been run yet. Enum values are looked up by name
# from the Inventor type library when possible; the numeric fallbacks below
# should be checked against Autodesk.Inventor.Interop.dll (REA's .NET metadata
# inspection can list them).

import sys

MM = 0.1  # Inventor API lengths are in cm

_FALLBACK = {
    "kPartDocumentObject": 12290,
    "kMetricSystemOfMeasure": 8963,
    "kJoinOperation": 20481,
    "kCutOperation": 20482,
    "kPositiveExtentDirection": 20993,
    "kNegativeExtentDirection": 20994,
    "kHorizontalDim": 19202,
    "kVerticalDim": 19203,
}
_INVENTOR_TLB = ("{D98A091D-3A0F-4C3E-B36E-61F62068D488}", 0, 1, 0)


def _constants():
    values = dict(_FALLBACK)
    try:
        from win32com.client import constants, gencache

        gencache.EnsureModule(*_INVENTOR_TLB)
        for name in values:
            try:
                values[name] = getattr(constants, name)
            except AttributeError:
                print(f"warning: {name} not in type library, using {values[name]}")
    except Exception as exc:  # type library unavailable: keep fallbacks
        print(f"warning: Inventor type library not loaded ({exc}); using numeric enums")
    return values


def connect():
    import pythoncom
    import win32com.client.dynamic as dyn

    try:
        unk = pythoncom.GetActiveObject("Inventor.Application")
        app = dyn.Dispatch(unk.QueryInterface(pythoncom.IID_IDispatch))
    except pythoncom.com_error:
        app = dyn.Dispatch("Inventor.Application")
    app.Visible = True
    return app


class Builder:
    def __init__(self, app, k):
        self.app, self.k = app, k
        self.tg = app.TransientGeometry
        template = app.FileManager.GetTemplateFile(
            k["kPartDocumentObject"], k["kMetricSystemOfMeasure"]
        )
        self.doc = app.Documents.Add(k["kPartDocumentObject"], template, True)
        self.cd = self.doc.ComponentDefinition
        self.xy = self.cd.WorkPlanes.Item(3)
        self.top = None
        self.warnings = []

    # -- helpers -------------------------------------------------------------

    def pt(self, x_mm, y_mm):
        return self.tg.CreatePoint2d(x_mm * MM, y_mm * MM)

    def sketch(self, plane):
        sk = self.cd.Sketches.Add(plane)
        origin = sk.AddByProjectingEntity(self.cd.WorkPoints.Item(1))
        return sk, origin

    def dim(self, sk, a, b, orientation, text_xy, expression):
        d = sk.DimensionConstraints.AddTwoPointDistance(
            a, b, self.k[orientation], self.pt(*text_xy)
        )
        d.Parameter.Expression = expression
        return d

    # -- operations ----------------------------------------------------------

    def parameter(self, name, expression):
        self.cd.Parameters.UserParameters.AddByExpression(name, str(expression), "mm")

    def plate(self, op):
        w, d = op["width_value"], op["depth_value"]
        sk, origin = self.sketch(self.xy)
        lines = sk.SketchLines.AddAsTwoPointRectangle(self.pt(0, 0), self.pt(w, d))
        horizontal = vertical = corner = None
        for i in range(1, lines.Count + 1):
            line = lines.Item(i)
            s, e = line.StartSketchPoint, line.EndSketchPoint
            if abs(s.Geometry.Y - e.Geometry.Y) < 1e-9 and horizontal is None:
                horizontal = line
            elif abs(s.Geometry.X - e.Geometry.X) < 1e-9 and vertical is None:
                vertical = line
            for p in (s, e):
                if abs(p.Geometry.X) < 1e-9 and abs(p.Geometry.Y) < 1e-9:
                    corner = p
        sk.GeometricConstraints.AddCoincident(origin, corner)
        self.dim(sk, horizontal.StartSketchPoint, horizontal.EndSketchPoint,
                 "kHorizontalDim", (w / 2, -10), op["width"])
        self.dim(sk, vertical.StartSketchPoint, vertical.EndSketchPoint,
                 "kVerticalDim", (-10, d / 2), op["depth"])
        prof = sk.Profiles.AddForSolid()
        feats = self.cd.Features.ExtrudeFeatures
        ed = feats.CreateExtrudeDefinition(prof, self.k["kJoinOperation"])
        ed.SetDistanceExtent(op["thickness"], self.k["kPositiveExtentDirection"])
        feats.Add(ed)
        self.top = self.cd.WorkPlanes.AddByPlaneAndOffset(self.xy, op["thickness"])
        self.top.Visible = False

    def corners(self, op):
        edges = self.app.TransientObjects.CreateEdgeCollection()
        body = self.cd.SurfaceBodies.Item(1)
        for i in range(1, body.Edges.Count + 1):
            e = body.Edges.Item(i)
            a, b = e.StartVertex.Point, e.StopVertex.Point
            if abs(a.X - b.X) < 1e-9 and abs(a.Y - b.Y) < 1e-9:
                edges.Add(e)
        if op["corner_type"] == "fillet":
            self.cd.Features.FilletFeatures.AddSimple(edges, op["size"])
        else:
            self.cd.Features.ChamferFeatures.AddUsingDistance(edges, op["size"])

    def holes(self, op):
        sk, origin = self.sketch(self.top)
        points = self.app.TransientObjects.CreateObjectCollection()
        for (xe, ye), (xv, yv) in zip(op["points"], op["values"]):
            p = sk.SketchPoints.Add(self.pt(xv, yv), True)
            self.dim(sk, origin, p, "kHorizontalDim", (xv / 2, yv + 5), xe)
            self.dim(sk, origin, p, "kVerticalDim", (xv + 5, yv / 2), ye)
            points.Add(p)
        hf = self.cd.Features.HoleFeatures
        placement = hf.CreateSketchPlacementDefinition(points)
        down = self.k["kNegativeExtentDirection"]
        diameter = op["diameter"]
        if op.get("thread"):
            try:
                diameter = hf.CreateTapInfo(True, "ISO Metric profile",
                                            op["thread"], "6H", True)
            except Exception as exc:
                self.warnings.append(
                    f"{op['id']}: tap info failed ({exc}); drilled at tap drill size")
        through = op["depth"] == "through"
        if op.get("cbore_diameter"):
            if through:
                hf.AddCBoreByThroughAllExtent(placement, diameter, op["cbore_diameter"],
                                              op["cbore_depth"], down)
            else:
                hf.AddCBoreByDistanceExtent(placement, diameter, op["cbore_diameter"],
                                            op["cbore_depth"], op["depth"], down, True)
        elif through:
            hf.AddDrilledByThroughAllExtent(placement, diameter, down)
        else:
            hf.AddDrilledByDistanceExtent(placement, diameter, op["depth"], down, True)

    def profile_cut(self, op):
        sk, _ = self.sketch(self.top)
        cx, cy, length, width, r = (op[k] for k in ("cx", "cy", "length", "width", "r"))
        if op["angle"] % 180:
            length, width = width, length
        hx, hy = length / 2, width / 2
        if r <= 0:
            sk.SketchLines.AddAsTwoPointRectangle(self.pt(cx - hx, cy - hy),
                                                  self.pt(cx + hx, cy + hy))
        else:
            # rounded outline: four corner arcs joined by straight lines
            centres = [(cx + hx - r, cy - hy + r), (cx + hx - r, cy + hy - r),
                       (cx - hx + r, cy + hy - r), (cx - hx + r, cy - hy + r)]
            starts = [(0, -r), (r, 0), (0, r), (-r, 0)]
            ends = [(r, 0), (0, r), (-r, 0), (0, -r)]
            arcs = [sk.SketchArcs.AddByCenterStartEndPoint(
                        self.pt(*c), self.pt(c[0] + s[0], c[1] + s[1]),
                        self.pt(c[0] + e[0], c[1] + e[1]), True)
                    for c, s, e in zip(centres, starts, ends)]
            for i, arc in enumerate(arcs):
                nxt = arcs[(i + 1) % 4]
                a, b = arc.EndSketchPoint, nxt.StartSketchPoint
                if abs(a.Geometry.X - b.Geometry.X) + abs(a.Geometry.Y - b.Geometry.Y) > 1e-9:
                    sk.SketchLines.AddByTwoPoints(a, b)
                else:
                    sk.GeometricConstraints.AddCoincident(a, b)
        self.warnings.append(
            f"{op['id']}: outline drawn at fixed size; only the depth is parametric")
        feats = self.cd.Features.ExtrudeFeatures
        ed = feats.CreateExtrudeDefinition(sk.Profiles.AddForSolid(), self.k["kCutOperation"])
        if op["depth"] == "through":
            ed.SetThroughAllExtent(self.k["kNegativeExtentDirection"])
        else:
            ed.SetDistanceExtent(op["depth"], self.k["kNegativeExtentDirection"])
        feats.Add(ed)


def run(plan, output=None):
    app = connect()
    b = Builder(app, _constants())
    for name, expression in plan["parameters"]:
        b.parameter(name, expression)
    for op in plan["operations"]:
        getattr(b, op["op"])(op)
    b.doc.Update()
    if output:
        b.doc.SaveAs(output, False)
        print(f"saved {output}")
    for w in b.warnings:
        print(f"warning: {w}")
    print(f"{plan['name']}: {len(plan['operations'])} operations done")


def main(plan):
    run(plan, sys.argv[1] if len(sys.argv) > 1 else None)
