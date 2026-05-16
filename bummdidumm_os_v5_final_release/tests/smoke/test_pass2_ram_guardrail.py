"""Static smoke tests for Pass 2 RAM guardrail (P2.2).

main_pass2.py must emit log.warning when records_to_index exceeds 50,000 —
not silently OOM-kill the Cloud Run task.
"""
from pathlib import Path


def _read_pass2() -> str:
    for p in [Path("main_pass2.py"),
              Path("bummdidumm_os_v5_final_release/main_pass2.py")]:
        if p.exists():
            return p.read_text(encoding="utf-8")
    raise FileNotFoundError("main_pass2.py not found")


class TestPass2RamGuardrail:

    def test_records_to_index_ram_warning_present(self):
        """P2.2: main_pass2.py must have a 50,000 threshold for the RAM guardrail."""
        source = _read_pass2()
        assert "records_to_index" in source, (
            "main_pass2.py must use records_to_index variable"
        )
        assert "50_000" in source or "50000" in source, (
            "main_pass2.py must check len(records_to_index) > 50_000 for RAM guardrail"
        )

    def test_records_to_index_warning_uses_log_warning(self):
        """P2.2: RAM guardrail must emit log.warning at the 50,000 threshold."""
        source = _read_pass2()
        if "50_000" in source:
            idx = source.index("50_000")
        else:
            idx = source.index("50000")
        surrounding = source[max(0, idx - 300):idx + 300]
        assert "warning" in surrounding.lower(), (
            "RAM guardrail near 50,000 threshold must call log.warning"
        )
