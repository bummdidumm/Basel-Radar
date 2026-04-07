"""Regression: main_apply_renames must use read_rows_chunked, not read_all_rows."""
import ast
from pathlib import Path


def test_apply_renames_uses_chunked_read():
    # Attempt both paths to work regardless of whether pytest is run from root or bummdidumm_os_v5_final_release
    p1 = Path("bummdidumm_os_v5_final_release/main_apply_renames.py")
    p2 = Path("main_apply_renames.py")
    target = p1 if p1.exists() else p2
    source = target.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "read_all_rows":
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and arg.value == "Dedupe_Report":
                        raise AssertionError(
                            "read_all_rows('Dedupe_Report') found — OOM risk. Use read_rows_chunked."
                        )
    assert "read_rows_chunked" in source, "read_rows_chunked must be present in main_apply_renames.py"
