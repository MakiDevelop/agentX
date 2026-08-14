from agentx.protocol import Risk
from agentx.tool_schemas import ollama_tools_from_registry, parse_signature
from agentx.tools import ToolRegistry


class _ReadTool:
    name = "read_file"
    description = "讀取檔案"
    risk = Risk.GREEN
    signature = "path, max_chars=20000"

    def run(self, args: dict) -> str:  # noqa: ANN001
        return ""


class _EditTool:
    name = "edit_file"
    description = "局部修改"
    risk = Risk.YELLOW
    signature = "path, edits=[{oldText, newText}]"

    def run(self, args: dict) -> str:  # noqa: ANN001
        return ""


def test_parse_signature_required_and_optional() -> None:
    properties, required = parse_signature("path, max_chars=20000")
    assert required == ["path"]
    assert properties["path"]["type"] == "string"
    assert properties["max_chars"]["type"] == "integer"


def test_parse_signature_array_default() -> None:
    properties, required = parse_signature("path, edits=[{oldText, newText}]")
    assert required == ["path"]
    assert properties["edits"]["type"] == "array"


def test_ollama_tools_include_registry_and_pseudo_tools() -> None:
    registry = ToolRegistry([_ReadTool(), _EditTool()])
    tools = ollama_tools_from_registry(registry)
    names = [item["function"]["name"] for item in tools]
    assert "read_file" in names
    assert "edit_file" in names
    assert "task_add" in names
    assert "task_list" in names
    read = next(item for item in tools if item["function"]["name"] == "read_file")
    assert read["function"]["parameters"]["required"] == ["path"]
