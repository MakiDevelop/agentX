from agentx.project_state import load_state, mark_guide_hint_seen, should_show_guide_hint


def test_guide_hint_is_shown_once_per_workspace(tmp_path) -> None:
    assert should_show_guide_hint(tmp_path) is True

    mark_guide_hint_seen(tmp_path)

    assert should_show_guide_hint(tmp_path) is False
    assert load_state(tmp_path)["guide_hint_seen"] is True


def test_corrupt_state_file_falls_back_to_empty_state(tmp_path) -> None:
    path = tmp_path / ".agentx" / "state.json"
    path.parent.mkdir(parents=True)
    path.write_text("{bad json", encoding="utf-8")

    assert load_state(tmp_path) == {}
    assert should_show_guide_hint(tmp_path) is True
