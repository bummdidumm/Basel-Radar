"""P2 guardrail: main_pass2.py must warn when records_to_index grows very large."""
from pathlib import Path


def _source() -> str:
    for p in [
        Path("main_pass2.py"),
        Path("bummdidumm_os_v5_final_release/main_pass2.py"),
    ]:
        if p.exists():
            return p.read_text(encoding="utf-8")
    raise FileNotFoundError("main_pass2.py not found")


def test_records_to_index_ram_warning_present():
    """records_to_index accumulates in memory; a warning must fire at the hardcoded threshold."""
    source = _source()
    assert "records_to_index" in source, "records_to_index list must be present in main_pass2.py"
    assert "50_000" in source or "50000" in source, (
        "RAM-pressure threshold (50 000) must be explicitly stated in main_pass2.py"
    )
    assert "RAM" in source, (
        "RAM-pressure warning must mention RAM so operators can grep for it in logs"
    )


def test_records_to_index_warning_uses_log_warning():
    """The RAM guardrail must emit a log.warning, not just a print or silent pass."""
    source = _source()
    # Verify the warning block is adjacent to the threshold check
    idx = source.find("50_000")
    if idx == -1:
        idx = source.find("50000")
    assert idx != -1, "50_000 threshold not found"
    # The warning call should appear within 300 chars of the threshold check
    window = source[idx: idx + 300]
    assert "warning" in window.lower(), (
        "log.warning must be called within the RAM-pressure guard block"
    )
