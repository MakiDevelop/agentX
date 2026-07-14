from pathlib import Path

from agentx.fidelity import fidelity_passed, format_fidelity_report, run_fidelity_probe


def test_fidelity_probe_current_repo_passes() -> None:
    checks = run_fidelity_probe(Path.cwd())

    assert fidelity_passed(checks)
    assert {check.id for check in checks} == {
        "agentx-md-present",
        "mt22-task-truth",
        "no-legacy-task-module",
        "bootstrap-loads-agentx-first",
        "bootstrap-loads-handoff",
        "learning-proposal-gate",
        "precommit-no-legacy-guard",
    }


def test_fidelity_probe_reports_missing_constitution(tmp_path: Path) -> None:
    checks = run_fidelity_probe(tmp_path)

    assert not fidelity_passed(checks)
    failed = {check.id for check in checks if not check.ok}
    assert "agentx-md-present" in failed
    assert "mt22-task-truth" in failed


def test_fidelity_report_marks_failures() -> None:
    checks = run_fidelity_probe(Path("/path/that/does/not/exist"))

    report = format_fidelity_report(checks)

    assert report.startswith("# agentX Fidelity Probe v0")
    assert "[FAIL] agentx-md-present" in report
