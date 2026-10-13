"""Recipe -> STEP -> recognised recipe, checked geometrically and by intent.

The flex tests are the point of the project: a recovered recipe must not
only rebuild the original, it must change the way the designer's recipe
changes when a driving dimension is edited.
"""

import pytest
from build123d import Location, export_step

from cadrecipe.build import build
from cadrecipe.recipe import Recipe, placement_points
from cadrecipe.recognize import recognize, recognize_solid
from cadrecipe.verify import compare, verify

from parts import ALL, bearing_bracket, mounting_plate


@pytest.fixture(scope="module")
def recovered(tmp_path_factory):
    out = {}
    for name, factory in ALL.items():
        truth = Recipe.from_dict(factory())
        step = tmp_path_factory.mktemp(name) / f"{name}.step"
        export_step(build(truth), str(step))
        recipe, normalized = recognize(step)
        out[name] = (truth, recipe, normalized)
    return out


@pytest.mark.parametrize("name", list(ALL))
def test_rebuilds_original_exactly(recovered, name):
    truth, recipe, normalized = recovered[name]
    assert "unrecognized" not in recipe.provenance
    recipe.validate()
    result = verify(recipe, normalized)
    assert result.ok, result.summary()


@pytest.mark.parametrize("name", list(ALL))
def test_same_feature_count_as_designer(recovered, name):
    truth, recipe, _ = recovered[name]
    def count(r):
        return sorted(f["type"] for f in r.features)
    assert count(recipe) == count(truth)


@pytest.mark.parametrize(
    "name, change",
    [
        ("mounting_plate", {"width": 300}),
        ("mounting_plate", {"depth": 150}),
        ("bearing_bracket", {"width": 220, "depth": 110}),
        ("odd_plate", {"depth": 90}),
    ],
)
def test_flex_follows_design_intent(recovered, name, change):
    truth, recipe, _ = recovered[name]
    expected = build(truth, change)
    actual = build(recipe, change)
    result = compare(expected, actual)
    assert result.ok, f"after {change}: {result.summary()}"


def test_mounting_plate_intent(recovered):
    _, recipe, _ = recovered["mounting_plate"]
    params = recipe.parameters
    assert params["corner_r"] == 8
    assert params["m8_clearance_margin"] == 20
    assert params["m8_clearance_pitch_x"] == "(width - 2*m8_clearance_margin) / 2"
    holes = {f["id"]: f for f in recipe.features if f["type"] == "hole"}
    assert holes["m8_clearance"]["spec"] == {"kind": "clearance", "size": "M8", "fit": "medium"}
    circle = holes["m6_tapped"]["at"]["circle"]
    assert circle["center"] == ["width/2", "depth/2"]
    assert params[circle["radius"]] == 30 and circle["start_angle"] == 45
    assert holes["m6_tapped"]["depth"] == 10


def test_counterbore_and_edge_referenced_row(recovered):
    _, recipe, _ = recovered["bearing_bracket"]
    by_id = {f["id"]: f for f in recipe.features}
    assert by_id["plate"]["corners"]["type"] == "chamfer"
    assert by_id["m10_counterbore"]["spec"] == {"kind": "counterbore", "size": "M10"}
    row = by_id["m5_tapped"]["at"]["grid"]
    assert row["origin"] == [40, "depth/2"] and row["count"] == [3, 1]


def test_non_standard_hole_is_kept_plain(recovered):
    _, recipe, _ = recovered["odd_plate"]
    pin = next(f for f in recipe.features if f["type"] == "hole")
    assert pin["spec"] == {"kind": "plain", "diameter": 7.3}
    assert pin["at"]["point"] == [22, "depth - 17"]


@pytest.mark.parametrize(
    "rotation", [(180, 0, 0), (0, 90, 0), (90, 0, 0)], ids=["upside_down", "on_x", "on_y"]
)
def test_orientation_does_not_matter(rotation):
    truth = Recipe.from_dict(bearing_bracket())
    solid = build(truth).solids()[0].moved(Location((13, -7, 42), rotation))
    recipe, normalized = recognize_solid(solid)
    assert "unrecognized" not in recipe.provenance
    assert verify(recipe, normalized).ok
    assert sorted(f["type"] for f in recipe.features) == ["hole", "hole", "plate"]


def test_unknown_geometry_is_reported_not_guessed():
    from build123d import Align, Box, Pos, Sphere

    plate = Box(100, 60, 10, align=(Align.MIN, Align.MIN, Align.MIN))
    dimpled = plate.cut(Pos(50, 30, 10) * Sphere(6))
    recipe, normalized = recognize_solid(dimpled.solids()[0])
    assert recipe.provenance["unrecognized"][0]["reason"].startswith("faces other than")
    assert not verify(recipe, normalized).ok


def test_placement_points_grid():
    truth = Recipe.from_dict(mounting_plate())
    env = truth.env()
    pts = placement_points(truth.features[1]["at"], env)
    assert pts[0] == (20, 20) and pts[-1] == (180, 100) and len(pts) == 6


def test_flex_check_catches_a_dead_copy(recovered):
    """Control: freeze every hole at its absolute position (what a plain STEP
    import gives you). It still rebuilds the original, but fails the flex
    test, which shows the flex test really measures intent."""
    truth, recipe, normalized = recovered["mounting_plate"]
    env = recipe.env()
    dead = Recipe.from_dict(recipe.to_dict())
    for feat in dead.features:
        if feat["type"] == "hole":
            pts = placement_points(feat["at"], env)
            feat["at"] = {"point": [round(pts[0][0], 6), round(pts[0][1], 6)]}
            dead.features += [
                {**feat, "id": f"{feat['id']}_{i}", "at": {"point": [round(x, 6), round(y, 6)]}}
                for i, (x, y) in enumerate(pts[1:], start=1)
            ]
    dead.validate()
    assert verify(dead, normalized).ok
    change = {"width": 300}
    assert not compare(build(truth, change), build(dead, change)).ok
