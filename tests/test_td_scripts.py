"""Comprobaciones estáticas de los scripts de TouchDesigner (no requieren TD)."""

import ast
from dataclasses import asdict
from pathlib import Path

import pytest

from editorial_solver import Weights

TD_DIR = Path(__file__).resolve().parent.parent / "TouchDesigner"


def _literal(path: Path, name: str):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} no está en {path.name}")


@pytest.mark.parametrize("script", sorted(TD_DIR.glob("*.py")), ids=lambda p: p.name)
def test_td_script_compiles(script):
    compile(script.read_text(encoding="utf-8"), str(script), "exec")


def test_weight_pars_match_solver_defaults():
    pars = _literal(TD_DIR / "build_network.py", "WEIGHT_PARS")
    defaults = {name[1:].lower(): value for name, _label, value in pars}
    assert defaults == asdict(Weights())


def test_par_exec_resolves_on_every_layout_par():
    par_exec = _literal(TD_DIR / "build_network.py", "PAR_EXEC")
    for name, _label, _value in _literal(TD_DIR / "build_network.py", "WEIGHT_PARS"):
        assert f"'{name}'" in par_exec
    assert "'Deterministic'" in par_exec


def test_extension_weight_pars_match_build():
    ext = _literal(TD_DIR / "EditorialSolverExt.py", "WEIGHT_PARS")
    build = _literal(TD_DIR / "build_network.py", "WEIGHT_PARS")
    assert set(ext.values()) == {name for name, _label, _value in build}
    assert set(ext) == set(asdict(Weights()))


def test_remove_replicant_callback_is_not_empty():
    """TD ignora un onRemoveReplicant vacío y destruye la réplica (verificado en TD)."""
    callbacks = _literal(TD_DIR / "build_network.py", "MEDIA_CALLBACKS")
    func = next(
        n
        for n in ast.parse(callbacks).body
        if isinstance(n, ast.FunctionDef) and n.name == "onRemoveReplicant"
    )
    assert any(not isinstance(stmt, ast.Return | ast.Pass) for stmt in func.body)
