import py_compile

from cadrecipe.recipe import Recipe
from cadrecipe.writers.inventor import plan, write_script

from parts import bearing_bracket, mounting_plate


def test_parameters_come_before_their_users():
    p = plan(Recipe.from_dict(mounting_plate()))
    order = [name for name, _ in p["parameters"]]
    assert order.index("width") < order.index("pitch_x")
    assert order.index("margin") < order.index("pitch_x")


def test_operations_keep_expressions():
    p = plan(Recipe.from_dict(mounting_plate()))
    ops = {op.get("id", op["op"]): op for op in p["operations"]}
    assert ops["plate"]["width"] == "width"
    assert ops["fixing"]["points"][1] == ["(margin) + (pitch_x)", "margin"]
    assert ops["fixing"]["diameter"] == "9 mm"
    assert ops["motor"]["thread"] == "M6x1" and ops["motor"]["depth"] == "10"
    assert ops["motor"]["points"][0][0] == "(width/2) + (bore_r) * cos(45 deg)"
    assert ops["adjust"]["r"] == 4.5


def test_counterbore_plan():
    p = plan(Recipe.from_dict(bearing_bracket()))
    cb = next(op for op in p["operations"] if op.get("id") == "fixing")
    assert cb["diameter"] == "11 mm" and cb["cbore_diameter"] == "18 mm"


def test_generated_script_compiles(tmp_path):
    out = write_script(Recipe.from_dict(mounting_plate()), tmp_path / "plate_inventor.py")
    py_compile.compile(str(out), doraise=True)
    assert "PLAN = {" in out.read_text()
