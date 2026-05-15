from agentx.attachments import extract_file_paths, format_attachment_context, read_attachments
from pypdf import PdfWriter


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


def test_read_png_attachment_metadata(tmp_path):
    path = tmp_path / "image.png"
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x02"
        b"\x00\x00\x00\x03"
        b"\x08\x02\x00\x00\x00"
    )

    context = format_attachment_context(read_attachments([path]))

    assert "image file: image.png" in context
    assert "dimensions=2x3" in context


def test_read_pdf_attachment_metadata(tmp_path):
    path = tmp_path / "blank.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with path.open("wb") as handle:
        writer.write(handle)

    context = format_attachment_context(read_attachments([path]))

    assert "pdf file: blank.pdf" in context
    assert "pages=1" in context
