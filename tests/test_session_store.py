from __future__ import annotations

import json
from pathlib import Path

from agentx.session_store import SessionEntry, SessionStore, fork_session


def test_session_entry_roundtrip() -> None:
    entry = SessionEntry(
        id="000001", role="user", content="hello",
        parent_id="000000", metadata={"key": "val"},
    )
    d = entry.to_dict()
    restored = SessionEntry.from_dict(d)
    assert restored.id == "000001"
    assert restored.role == "user"
    assert restored.content == "hello"
    assert restored.parent_id == "000000"
    assert restored.metadata == {"key": "val"}


def test_session_entry_to_message() -> None:
    entry = SessionEntry(id="0", role="assistant", content="hi")
    msg = entry.to_message()
    assert msg == {"role": "assistant", "content": "hi"}


def test_session_store_create_writes_header(tmp_path: Path) -> None:
    store = SessionStore.create(tmp_path, model="test-model", namespace="ns")
    assert store.path.exists()
    assert len(store.entries) == 1
    assert store.entries[0].role == "system"
    assert "session_start" in store.entries[0].content


def test_session_store_append_and_replay(tmp_path: Path) -> None:
    store = SessionStore.create(tmp_path)
    store.append("user", "question 1")
    store.append("assistant", "answer 1")
    store.append("user", "question 2")

    messages = store.replay()
    assert len(messages) == 4  # header + 3
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == "question 1"
    assert messages[2]["role"] == "assistant"


def test_session_store_load_existing(tmp_path: Path) -> None:
    path = tmp_path / "test.jsonl"
    lines = [
        json.dumps({"id": "000000", "ts": "2026-01-01T00:00:00", "role": "system", "content": "start"}),
        json.dumps({"id": "000001", "ts": "2026-01-01T00:00:01", "role": "user", "content": "hi"}),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    store = SessionStore.load(path)
    assert len(store.entries) == 2
    assert store.entries[1].content == "hi"


def test_session_store_replay_up_to_id(tmp_path: Path) -> None:
    store = SessionStore.create(tmp_path)
    e1 = store.append("user", "q1")
    store.append("assistant", "a1")
    store.append("user", "q2")

    messages = store.replay(up_to_id=e1.id)
    assert len(messages) == 2  # header + q1


def test_session_store_generates_sequential_ids(tmp_path: Path) -> None:
    store = SessionStore.create(tmp_path)
    e1 = store.append("user", "a")
    e2 = store.append("user", "b")
    assert int(e1.id) < int(e2.id)


def test_session_store_persists_to_disk(tmp_path: Path) -> None:
    store = SessionStore.create(tmp_path, model="m", namespace="n")
    store.append("user", "hello")

    reloaded = SessionStore.load(store.path)
    assert len(reloaded.entries) == 2
    assert reloaded.entries[1].content == "hello"


def test_fork_session_copies_up_to_entry(tmp_path: Path) -> None:
    store = SessionStore.create(tmp_path)
    store.append("user", "q1")
    e2 = store.append("assistant", "a1")
    store.append("user", "q2")
    store.append("assistant", "a2")

    forked = fork_session(store.path, from_entry_id=e2.id, workspace=tmp_path)
    # +1 for the explicit "forked ..." system marker we insert for traceability
    # (improvement over the original create-only header behavior)
    assert len(forked.entries) == 4  # fork-marker + header + q1 + a1
    assert forked.path != store.path
    assert forked.entries[-1].content == "a1"
    # The first entry should be our fork marker (not the original create header)
    assert "forked from" in forked.entries[0].content
    assert forked.entries[0].metadata.get("event") == "fork"


def test_fork_session_creates_new_file(tmp_path: Path) -> None:
    store = SessionStore.create(tmp_path)
    store.append("user", "x")
    e = store.append("user", "y")

    forked = fork_session(store.path, from_entry_id=e.id, workspace=tmp_path)
    assert forked.path != store.path
    assert forked.path.exists()


def test_session_store_handles_corrupt_lines(tmp_path: Path) -> None:
    path = tmp_path / "corrupt.jsonl"
    path.write_text(
        '{"id":"000000","ts":"t","role":"system","content":"ok"}\n'
        "not valid json\n"
        '{"id":"000001","ts":"t","role":"user","content":"hi"}\n',
        encoding="utf-8",
    )
    store = SessionStore.load(path)
    assert len(store.entries) == 2


def test_persistence_in_agent_session(tmp_path: Path) -> None:
    from agentx.config import Settings
    from agentx.loop import AgentSession
    from agentx.tools import ToolRegistry, builtin_tools

    class FakeOllama:
        model = "fake"
        def chat(self, messages, *, json_mode=False, on_delta=None, cancel_event=None):
            return '{"type":"final","content":"done"}'

    class FakeMemory:
        def search(self, query, namespace="shared", limit=5):
            return "[]"
        def write(self, content, namespace="agent:agentx"):
            return "ok"

    settings = Settings.from_values(
        model="fake", ollama_url="http://localhost:11434", ollama_timeout=60,
        memory_hall_url="http://localhost:9100", memory_hall_token=None,
        max_steps=5, context_limit_tokens=8192, auto_handoff=False,
        persona="default", workspace=tmp_path, learning_enabled=False,
    )
    ollama = FakeOllama()
    memory = FakeMemory()
    registry = ToolRegistry(builtin_tools(tmp_path, memory))  # type: ignore[arg-type]
    session = AgentSession(
        settings=settings, ollama=ollama, tools=registry,  # type: ignore[arg-type]
        memory=memory,  # type: ignore[arg-type]
    )
    session.enable_persistence()
    session.ask("test prompt")

    store = SessionStore.load(session._session_store.path)
    roles = [e.role for e in store.entries]
    assert "user" in roles
    assert "assistant" in roles
