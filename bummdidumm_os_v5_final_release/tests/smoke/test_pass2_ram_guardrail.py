"""Smoke checks for Pass-2 RAM guardrail documentation contract."""

import ast
from pathlib import Path


def _load_pass2_source() -> str:
    for p in [Path("main_pass2.py"), Path("bummdidumm_os_v5_final_release/main_pass2.py")]:
        if p.exists():
            return p.read_text(encoding="utf-8")
    raise FileNotFoundError("main_pass2.py not found")


def test_pass2_contains_records_to_index_warning_threshold():
    source = _load_pass2_source()
    tree = ast.parse(source)
    found_threshold = False

    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if not isinstance(test, ast.Compare):
            continue
        if len(test.ops) != 1 or not isinstance(test.ops[0], ast.Gt):
            continue
        if len(test.comparators) != 1 or not isinstance(test.comparators[0], ast.Constant):
            continue
        if test.comparators[0].value != 50_000:
            continue
        if not (isinstance(test.left, ast.Call) and isinstance(test.left.func, ast.Name) and test.left.func.id == "len"):
            continue
        if not test.left.args or not isinstance(test.left.args[0], ast.Name):
            continue
        if test.left.args[0].id == "records_to_index":
            found_threshold = True
            break

    assert found_threshold, "Pass 2 must keep guardrail condition len(records_to_index) > 50_000"


def test_pass2_guardrail_warns_via_log_warning():
    source = _load_pass2_source()
    tree = ast.parse(source)
    found_warning = False

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Attribute) and node.func.attr == "warning"):
            continue
        if not (isinstance(node.func.value, ast.Name) and node.func.value.id == "log"):
            continue
        if not node.args or not isinstance(node.args[0], ast.Constant):
            continue
        msg = node.args[0].value
        if isinstance(msg, str) and "records_to_index" in msg:
            found_warning = True
            break

    assert found_warning, "Pass 2 guardrail must log a warning mentioning records_to_index"
