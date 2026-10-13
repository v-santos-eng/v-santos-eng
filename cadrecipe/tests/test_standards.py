from cadrecipe.standards import hole_geometry, match_counterbore, match_simple_hole


def test_clearance_and_tap_drill():
    assert match_simple_hole(9.0).spec == {"kind": "clearance", "size": "M8", "fit": "medium"}
    assert match_simple_hole(6.8).spec == {"kind": "tapped", "size": "M8"}


def test_ambiguous_diameter_reports_alternative():
    m = match_simple_hole(17.5)
    assert m.spec["size"] == "M16" and m.spec["kind"] == "clearance"
    assert any("M20" in alt for alt in m.alternatives)


def test_unknown_diameter_stays_plain():
    assert match_simple_hole(7.3).spec == {"kind": "plain", "diameter": "7.3"}


def test_counterbore_round_trip():
    geo = hole_geometry({"kind": "counterbore", "size": "M8"})
    m = match_counterbore(geo.diameter, geo.cbore_diameter, geo.cbore_depth)
    assert m.spec == {"kind": "counterbore", "size": "M8"}
