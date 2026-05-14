from agentx.git_workflow import parse_status_files


def test_parse_status_files() -> None:
    status = """## main...origin/main
 M README.md
?? src/new.py
D  old.txt
R  a.txt -> b.txt
"""
    assert parse_status_files(status) == ["README.md", "src/new.py", "old.txt", "a.txt", "b.txt"]
