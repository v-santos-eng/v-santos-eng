"""Safe evaluation of parameter expressions.

Recipes store every dimension as an expression string ("width - 2*margin")
so that intent survives the trip between CAD systems. Only arithmetic and a
small set of math functions are allowed; anything else is rejected.
"""

from __future__ import annotations

import ast
import math
import operator
from collections.abc import Mapping

Number = int | float
Expr = str | int | float

_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
}
_UNARYOPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCS = {
    "abs": abs,
    "min": min,
    "max": max,
    "round": round,
    "sqrt": math.sqrt,
    "sin": lambda deg: math.sin(math.radians(deg)),
    "cos": lambda deg: math.cos(math.radians(deg)),
    "tan": lambda deg: math.tan(math.radians(deg)),
}


class ExpressionError(ValueError):
    pass


def names_in(expr: Expr) -> set[str]:
    """Parameter names referenced by an expression."""
    if isinstance(expr, (int, float)):
        return set()
    tree = _parse(expr)
    return {
        n.id
        for n in ast.walk(tree)
        if isinstance(n, ast.Name) and n.id not in _FUNCS
    }


def evaluate(expr: Expr, env: Mapping[str, Number]) -> float:
    if isinstance(expr, bool):
        raise ExpressionError(f"boolean is not a valid expression: {expr!r}")
    if isinstance(expr, (int, float)):
        return float(expr)
    return float(_eval(_parse(expr).body, env, expr))


def resolve_parameters(params: Mapping[str, Expr]) -> dict[str, float]:
    """Evaluate all parameters in dependency order; detects cycles."""
    values: dict[str, float] = {}
    visiting: set[str] = set()

    def visit(name: str) -> float:
        if name in values:
            return values[name]
        if name not in params:
            raise ExpressionError(f"unknown parameter: {name}")
        if name in visiting:
            raise ExpressionError(f"circular parameter reference at: {name}")
        visiting.add(name)
        for dep in names_in(params[name]):
            visit(dep)
        visiting.discard(name)
        values[name] = evaluate(params[name], values)
        return values[name]

    for name in params:
        visit(name)
    return values


def _parse(expr: str) -> ast.Expression:
    try:
        return ast.parse(str(expr), mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(f"invalid expression {expr!r}: {exc.msg}") from exc


def _eval(node: ast.AST, env: Mapping[str, Number], src: str) -> Number:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.Name):
        if node.id not in env:
            raise ExpressionError(f"unknown parameter {node.id!r} in {src!r}")
        return env[node.id]
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        return _BINOPS[type(node.op)](
            _eval(node.left, env, src), _eval(node.right, env, src)
        )
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARYOPS:
        return _UNARYOPS[type(node.op)](_eval(node.operand, env, src))
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in _FUNCS
        and not node.keywords
    ):
        args = [_eval(a, env, src) for a in node.args]
        return _FUNCS[node.func.id](*args)
    raise ExpressionError(f"unsupported syntax in {src!r}: {ast.dump(node)[:60]}")


def fmt(value: float, ndigits: int = 3) -> str:
    """Shortest decimal text for a dimension: 20.0 -> '20', 12.5 -> '12.5'."""
    v = round(value, ndigits)
    if v == 0:
        v = 0.0  # avoid '-0'
    text = f"{v:.{ndigits}f}".rstrip("0").rstrip(".")
    return text or "0"
