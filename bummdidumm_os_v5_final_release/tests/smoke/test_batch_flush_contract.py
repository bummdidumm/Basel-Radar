"""Regression: batch flush in apply scripts must pass request objects to _execute_with_backoff.

_execute_with_backoff(request_op) calls request_op.execute() internally, so it requires
a Google API request object — not a Python function reference and not the result of
calling such a function. This test uses AST analysis to enforce the correct pattern.
"""
import ast
from pathlib import Path


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read(rel: str) -> str:
    p = _root() / rel
    return p.read_text(encoding="utf-8")


def _find_bad_execute_with_backoff_calls(source: str) -> list[str]:
    """Return descriptions of any _execute_with_backoff calls that pass the wrong argument type.

    Bad patterns:
      - Passing a Name node (bare function reference): _execute_with_backoff(some_func)
      - Passing the result of calling a wrapper function:
          _execute_with_backoff(_batch()) or _execute_with_backoff(_batch_final())
    Good pattern:
      - Passing an inline call chain ending in .batchUpdate(...):
          _execute_with_backoff(service.spreadsheets().values().batchUpdate(...))
    """
    tree = ast.parse(source)
    issues = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # Match calls on _execute_with_backoff
        if not (isinstance(func, ast.Attribute) and func.attr == "_execute_with_backoff"):
            continue
        if not node.args:
            continue
        arg = node.args[0]

        # BAD: bare Name node — e.g. _execute_with_backoff(_batch_update_1)
        if isinstance(arg, ast.Name):
            issues.append(
                f"line {node.lineno}: _execute_with_backoff receives a bare function "
                f"reference '{arg.id}' — must be an inline request object"
            )
            continue

        # BAD: Call node whose func is a Name — e.g. _execute_with_backoff(_batch())
        if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name):
            issues.append(
                f"line {node.lineno}: _execute_with_backoff receives the result of "
                f"calling wrapper function '{arg.func.id}()' — must be an inline request object"
            )
            continue

        # GOOD: Call chain — verify it ends in .batchUpdate or another Sheets API method
        # (method chain = nested ast.Call / ast.Attribute nodes)
        # We just verify the outermost call is an Attribute call (method call), not a Name call.
        if isinstance(arg, ast.Call) and not isinstance(arg.func, ast.Attribute):
            issues.append(
                f"line {node.lineno}: _execute_with_backoff argument is a Call but not "
                f"a method call — expected inline API request chain"
            )

    return issues


def test_apply_renames_batch_flush_contract():
    source = _read("main_apply_renames.py")
    issues = _find_bad_execute_with_backoff_calls(source)
    assert not issues, (
        "main_apply_renames.py has invalid _execute_with_backoff call(s):\n"
        + "\n".join(issues)
    )


def test_apply_sort_batch_flush_contract():
    source = _read("main_apply_sort.py")
    issues = _find_bad_execute_with_backoff_calls(source)
    assert not issues, (
        "main_apply_sort.py has invalid _execute_with_backoff call(s):\n"
        + "\n".join(issues)
    )


def test_no_wrapper_function_names_remain_apply_renames():
    """Structural: wrapper functions _batch / _batch_final must be gone."""
    source = _read("main_apply_renames.py")
    for forbidden in ("def _batch(", "def _batch_final(", "_batch()", "_batch_final()"):
        assert forbidden not in source, (
            f"main_apply_renames.py still contains forbidden pattern: {forbidden!r}"
        )


def test_no_wrapper_function_names_remain_apply_sort():
    """Structural: wrapper functions _batch_update_1 / _batch_update_2 must be gone."""
    source = _read("main_apply_sort.py")
    for forbidden in (
        "def _batch_update_1(",
        "def _batch_update_2(",
        "_batch_update_1",
        "_batch_update_2",
    ):
        assert forbidden not in source, (
            f"main_apply_sort.py still contains forbidden pattern: {forbidden!r}"
        )
