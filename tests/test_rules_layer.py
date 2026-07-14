import importlib.util
from pathlib import Path


def _load_rule_module():
    script = Path(__file__).resolve().parents[1] / "scripts" / "check_no_legacy_task.py"
    spec = importlib.util.spec_from_file_location("check_no_legacy_task", script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


find_legacy_task_violations = _load_rule_module().find_legacy_task_violations


def test_no_legacy_task_guard_accepts_tasks_api(tmp_path: Path) -> None:
    src = tmp_path / "src" / "agentx"
    src.mkdir(parents=True)
    (src / "cli.py").write_text("from agentx.tasks import load_tasks\n", encoding="utf-8")

    assert find_legacy_task_violations(tmp_path / "src") == []


def test_no_legacy_task_guard_rejects_module_file(tmp_path: Path) -> None:
    src = tmp_path / "src" / "agentx"
    src.mkdir(parents=True)
    (src / "task.py").write_text("# legacy\n", encoding="utf-8")

    violations = find_legacy_task_violations(tmp_path / "src")

    assert any("legacy module file must not exist" in violation for violation in violations)


def test_no_legacy_task_guard_rejects_absolute_imports(tmp_path: Path) -> None:
    src = tmp_path / "src" / "agentx"
    src.mkdir(parents=True)
    (src / "bad.py").write_text(
        "import agentx.task\nfrom agentx.task import TaskState\nfrom agentx import task\n",
        encoding="utf-8",
    )

    violations = find_legacy_task_violations(tmp_path / "src")

    assert len(violations) == 3
    assert all("forbidden" in violation for violation in violations)


def test_no_legacy_task_guard_rejects_relative_import_inside_package(tmp_path: Path) -> None:
    src = tmp_path / "src" / "agentx"
    src.mkdir(parents=True)
    (src / "bad.py").write_text("from .task import TaskState\n", encoding="utf-8")

    violations = find_legacy_task_violations(tmp_path / "src")

    assert violations == [f"{src / 'bad.py'}:1: forbidden relative import from .task"]
