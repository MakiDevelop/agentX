from agentx.attachments import extract_file_paths, format_attachment_context, read_attachments


def test_extract_dragged_absolute_path(tmp_path):
    path = tmp_path / "hello world.txt"
    path.write_text("hello", encoding="utf-8")

    paths = extract_file_paths(f"請讀 '{path}'", tmp_path)

    assert paths == [path.resolve()]


def test_extract_workspace_relative_path(tmp_path):
    path = tmp_path / "README.md"
    path.write_text("hello", encoding="utf-8")

    paths = extract_file_paths("請讀 README.md", tmp_path)

    assert paths == [path.resolve()]


def test_extract_escaped_dragged_path(tmp_path):
    path = tmp_path / "hello world.txt"
    path.write_text("hello", encoding="utf-8")
    escaped = str(path).replace(" ", "\\ ")

    paths = extract_file_paths(f"請讀 {escaped}", tmp_path)

    assert paths == [path.resolve()]


def test_format_attachment_context(tmp_path):
    path = tmp_path / "note.txt"
    path.write_text("content", encoding="utf-8")

    context = format_attachment_context(read_attachments([path]))

    assert "Attached file context:" in context
    assert str(path) in context
    assert "content" in context
