"""Smoke checks for Pass-2 RAM guardrail documentation contract."""

from pathlib import Path


def _load_pass2_source() -> str:
    for p in [Path("main_pass2.py"), Path("bummdidumm_os_v5_final_release/main_pass2.py")]:
        if p.exists():
            return p.read_text(encoding="utf-8")
    raise FileNotFoundError("main_pass2.py not found")


def test_pass2_contains_records_to_index_warning_threshold():
    source = _load_pass2_source()
    assert "if len(records_to_index) > 50_000" in source


def test_pass2_guardrail_warns_via_log_warning():
    source = _load_pass2_source()
    assert 'log.warning("Pass 2 records_to_index sehr groß' in source
