import pytest

from cadrecipe.expr import ExpressionError, evaluate, fmt, names_in, resolve_parameters


def test_arithmetic_and_functions():
    env = {"w": 200, "m": 20}
    assert evaluate("(w - 2*m) / 2", env) == 80
    assert evaluate("sqrt(16) + max(1, 2)", {}) == 6
    assert evaluate("cos(60)", {}) == pytest.approx(0.5)


def test_resolve_in_dependency_order():
    params = {"pitch": "(width - 2*margin) / 2", "width": 200, "margin": 20}
    assert resolve_parameters(params)["pitch"] == 80


def test_cycle_and_unknown_are_errors():
    with pytest.raises(ExpressionError, match="circular"):
        resolve_parameters({"a": "b + 1", "b": "a"})
    with pytest.raises(ExpressionError, match="unknown"):
        resolve_parameters({"a": "missing * 2"})


@pytest.mark.parametrize("src", ["__import__('os')", "w.real", "[1, 2]", "lambda: 1"])
def test_rejects_non_arithmetic(src):
    with pytest.raises(ExpressionError):
        evaluate(src, {"w": 1})


def test_names_and_formatting():
    assert names_in("width/2 + sqrt(margin)") == {"width", "margin"}
    assert fmt(20.0) == "20" and fmt(12.5) == "12.5" and fmt(-0.0001) == "0"
