from cadrecipe.cli import main

from parts import EXAMPLES


def test_build_recognize_verify(tmp_path, capsys):
    recipe = EXAMPLES / "mounting_plate.cadrecipe.json"
    step = tmp_path / "plate.step"
    assert main(["build", str(recipe), "-o", str(step), "--set", "width=240"]) == 0
    out = tmp_path / "plate.cadrecipe.json"
    assert main(["recognize", str(step), "-o", str(out)]) == 0
    assert "MATCH" in capsys.readouterr().out
    assert main(["verify", str(out), str(step)]) == 0
    assert main(["inventor", str(out), "-o", str(tmp_path / "p.py")]) == 0
