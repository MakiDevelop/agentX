from unittest.mock import MagicMock, patch

import pytest

from agentx.memory_hall import (
    AmhClient,
    MemoryHallClient,
    NullMemoryClient,
    memory_read_payload,
    memory_status_payload,
    memory_write_payload,
)
from agentx.tools.builtin import MemoryWriteTool


class TestNullMemoryClient:
    def test_null_memory_client_is_read_write_noop(self):
        client = NullMemoryClient()

        assert client.disabled is True
        assert client.search("anything", namespace="project:test") == "[]"
        assert "write skipped" in client.write("content", namespace="project:test")
        assert client.list_entries("project:test") == []
        assert client.audit("mem-1") == []

    def test_null_memory_client_supports_aca_and_structured_interfaces(self):
        client = NullMemoryClient()

        aca = client.write_aca(
            content="content",
            namespace="project:test",
            memory_type="fact",
            source_tier="human_confirmed",
        )
        structured = client.write_structured(
            content="content",
            namespace="project:test",
            entry_type="fact",
            summary="summary",
            tags=["test"],
        )
        upgrade = client.tier_upgrade("mem-1", confirmed_by="human:maki")

        assert aca["status"] == "disabled"
        assert aca["memory_id"] == "memory-disabled"
        assert structured["status"] == "disabled"
        assert upgrade["status"] == "disabled"


class TestWriteAca:
    def test_write_aca_builds_correct_aca_payload(self, monkeypatch):
        client = MemoryHallClient("http://example.com", token="t")
        captured = {}

        def fake_post(url, headers=None, json=None):
            captured["url"] = url
            captured["json"] = json
            class Resp:
                def raise_for_status(self): pass
                def json(self): return {"memory_id": "fake-123"}
            return Resp()

        monkeypatch.setattr("httpx.Client.post", fake_post, raising=False)
        # Patch the context manager usage
        with patch("httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_client.post.side_effect = fake_post

            resp = client.write_aca(
                content="Use PostgreSQL for the user store. Rationale: team expertise.",
                namespace="project:agentX",
                memory_type="decision",
                source_tier="llm_derived",
                agent_id="agentx",
                summary="Postgres decision",
                tags=["decision", "db"],
            )

        payload = captured.get("json") or mock_client.post.call_args.kwargs.get("json", {})
        assert payload["namespace"] == "project:agentX"
        assert payload["type"] == "decision"
        assert payload["content"] == "Use PostgreSQL for the user store. Rationale: team expertise."
        assert "metadata" in payload
        meta = payload["metadata"]
        assert meta["aca_version"] == "0.1"
        assert meta["source_tier"] == "llm_derived"
        assert meta["source_type"] == "agent"
        assert "source_ref" in meta
        assert "content_hash" in meta
        assert meta["hash_algorithm"] == "sha256"
        assert "anti_ouroboros" in meta
        assert resp["memory_id"] == "fake-123"

    def test_write_aca_rejects_invalid_tier(self):
        client = MemoryHallClient("http://example.com")
        with pytest.raises(ValueError, match="source_tier must be one of"):
            client.write_aca(
                content="bad",
                namespace="project:agentX",
                source_tier="invalid_tier",
            )

    def test_write_aca_rejects_invalid_memory_type(self):
        client = MemoryHallClient("http://example.com")
        with pytest.raises(ValueError, match="memory_type must be one of"):
            client.write_aca(
                content="bad",
                namespace="project:agentX",
                memory_type="invalid_type",
            )

    def test_write_aca_includes_flat_keys_for_amh_adapter(self):
        client = MemoryHallClient("http://example.com")
        captured = {}

        def fake_post(url, headers=None, json=None):
            captured["json"] = json
            class Resp:
                def raise_for_status(self): pass
                def json(self): return {"memory_id": "id"}
            return Resp()

        with patch("httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_client.post.side_effect = fake_post

            client.write_aca(
                content="test content for flat keys",
                namespace="project:foo",
                memory_type="lesson",
                source_tier="human_confirmed",
            )

        payload = captured["json"]
        meta = payload["metadata"]
        # Flat keys required by AMH memhall adapter (per Codex review)
        assert "source_type" in meta
        assert "source_ref" in meta
        assert "source_tier" in meta
        # Also keep rich form
        assert "source" in meta
        assert meta["source"]["tier"] == "human_confirmed"


class TestMemoryWriteToolAca:
    def test_memory_write_tool_with_tier_uses_write_aca(self):
        fake_memory = MagicMock()
        fake_memory.write_aca.return_value = {
            "entry_id": "aca-999",
            "governance_applied": [{"rule": "aca_tier"}],
        }
        tool = MemoryWriteTool(fake_memory)

        result = tool.run({
            "content": "Important human fact",
            "namespace": "project:agentX",
            "tier": "human_confirmed",
            "memory_type": "fact",
        })

        assert "aca_write ok" in result
        fake_memory.write_aca.assert_called_once()
        call_kwargs = fake_memory.write_aca.call_args.kwargs
        assert call_kwargs["source_tier"] == "human_confirmed"
        assert call_kwargs["memory_type"] == "fact"

    def test_memory_write_tool_without_tier_uses_legacy_write(self):
        fake_memory = MagicMock()
        fake_memory.write.return_value = "legacy-ok"
        tool = MemoryWriteTool(fake_memory)

        result = tool.run({
            "content": "plain note without tier",
            "namespace": "project:agentX",
        })

        assert result == "legacy-ok"
        fake_memory.write.assert_called_once_with(
            content="plain note without tier",
            namespace="project:agentX",
        )
        fake_memory.write_aca.assert_not_called()

    def test_memory_write_tool_explicit_tier_fails_closed_on_write_aca_error(self):
        fake_memory = MagicMock()
        fake_memory.write_aca.side_effect = RuntimeError("simulated AMH rejection")
        tool = MemoryWriteTool(fake_memory)

        with pytest.raises(RuntimeError, match="simulated AMH rejection"):
            tool.run({
                "content": "this should not fallback",
                "tier": "llm_derived",
            })


class TestAmhClient:
    """More complete tests for AmhClient using mocks for amh CLI (subprocess)."""

    def test_amh_client_write_uses_cli(self, monkeypatch):
        # Patch shutil.which BEFORE instantiating (it runs in __init__)
        monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/amh" if x == "amh" else None)

        client = AmhClient(store="json", store_path="/tmp/test-amh.json")
        captured = {}

        def fake_run(cmd, input=None, capture_output=True, timeout=None, check=False):
            captured["cmd"] = cmd
            captured["input"] = input
            class Result:
                returncode = 0
                stdout = b"written"
                stderr = b""
            return Result()

        monkeypatch.setattr("subprocess.run", fake_run)

        out = client.write("test content for write", namespace="project:foo")

        assert "written" in out
        assert captured["cmd"][0] == "amh"
        assert "--store" in captured["cmd"]
        assert "json" in captured["cmd"]
        assert "--caller-ns" in captured["cmd"]
        assert "project:foo" in captured["cmd"]
        # Content appears as a CLI argument (before the --store flags which are appended later)
        assert "test content for write" in captured["cmd"]

    def test_amh_client_search_filters_results(self, monkeypatch):
        # Patch before client creation
        monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/amh")

        client = AmhClient()
        output_lines = [
            "some irrelevant line",
            "important decision about postgres",
            "another line with query",
            "query keyword here"
        ]

        def fake_run(cmd, input=None, capture_output=True, timeout=None, check=False):
            class Result:
                returncode = 0
                stdout = "\n".join(output_lines).encode()
                stderr = b""
            return Result()

        monkeypatch.setattr("subprocess.run", fake_run)

        result = client.search("query", namespace="project:bar", limit=5)

        assert "query keyword here" in result
        assert "another line with query" in result
        # Irrelevant filtered out in basic impl
        assert "some irrelevant line" not in result

    def test_amh_client_tier_upgrade_falls_back_on_error(self, monkeypatch):
        # Patch before client creation
        monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/amh")

        client = AmhClient()
        calls = []

        def fake_run(cmd, input=None, capture_output=True, timeout=None, check=False):
            calls.append(cmd)
            class Result:
                returncode = 1  # simulate failure of native tier-upgrade subcommand
                stdout = b""
                stderr = b"unknown subcommand"
            return Result()

        monkeypatch.setattr("subprocess.run", fake_run)

        # Patch write_structured to capture fallback
        def capture_write_structured(**kwargs):
            calls.append(("fallback", kwargs))
            return {"status": "ok", "memory_id": "fallback-id"}
        client.write_structured = capture_write_structured

        resp = client.tier_upgrade(
            "mem-123",
            new_tier="human_confirmed",
            confirmed_by="human:maki",
            method="human_review",
            evidence_ids=["ev1"],
            namespace="project:test",
        )

        assert resp["status"] == "ok"
        # First call was the failing tier-upgrade attempt
        assert any("tier-upgrade" in str(c) for c in calls)
        # Then fallback happened
        assert any(c[0] == "fallback" for c in calls if isinstance(c, tuple))

    def test_amh_client_audit_best_effort(self, monkeypatch):
        # Patch before client creation
        monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/amh")

        client = AmhClient()
        mock_output = "line with mem-456\nirrelevant\nanother with mem-456"

        def fake_run(cmd, input=None, capture_output=True, timeout=None, check=False):
            class Result:
                returncode = 0
                stdout = mock_output.encode()
                stderr = b""
            return Result()

        monkeypatch.setattr("subprocess.run", fake_run)

        events = client.audit("mem-456")

        assert len(events) >= 2
        assert all("mem-456" in str(e) for e in events)

    def test_amh_client_different_stores_build_correct_flags(self, monkeypatch):
        """Verify expanded --store support for json, sqlite, postgres, memhall etc."""
        monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/amh")

        test_cases = [
            ("json", "/tmp/m.json", ["--store", "json", "--path", "/tmp/m.json"]),
            ("sqlite", "/tmp/m.db", ["--store", "sqlite", "--path", "/tmp/m.db"]),
            ("postgres", "postgres://user:pass@host/db", ["--store", "postgres", "--path", "postgres://user:pass@host/db"]),
            ("memhall", "http://100.89.41.50:9100", ["--store", "memhall", "--path", "http://100.89.41.50:9100"]),
        ]

        for store, path, expected in test_cases:
            captured = {}
            def fake_run(cmd, **kwargs):
                captured["cmd"] = cmd
                class R:
                    returncode = 0
                    stdout = b"ok"
                    stderr = b""
                return R()
            monkeypatch.setattr("subprocess.run", fake_run)

            client = AmhClient(store=store, store_path=path)
            client.write("test content", namespace="p:storetest")

            for flag in expected:
                assert flag in captured["cmd"], f"store={store} missing flag {flag}"
            assert "--caller-ns" in captured["cmd"]
            assert "p:storetest" in captured["cmd"]
            # cmd should start with amh + the write args + store flags
            assert captured["cmd"][0] == "amh"
            assert "write" in captured["cmd"]


class TestMemoryStatusPayload:
    def test_memory_status_payload_reports_memhall_without_secret(self, tmp_path, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda name: None)

        payload = memory_status_payload(
            workspace=tmp_path,
            namespace="project:test",
            memory_backend="memhall",
            memory_hall_url="http://127.0.0.1:9100",
            memory_hall_token="secret-token",
        )

        assert payload["schema"] == "agentx.memory_status.v1"
        assert payload["ok"] is True
        assert payload["memory_backend"] == "memhall"
        assert payload["legacy_memhall"]["token"] == "set"
        assert payload["amh"]["available"] is False
        assert "secret-token" not in str(payload)

    def test_memory_status_payload_blocks_amh_when_cli_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda name: None)

        payload = memory_status_payload(
            workspace=tmp_path,
            namespace="project:test",
            memory_backend="amh",
            memory_amh_store="json",
        )

        assert payload["ok"] is False
        assert payload["blockers"] == ["amh_cli_unavailable"]
        assert payload["amh"]["path"].endswith(".agentx/amh/memory.json")

    def test_memory_status_payload_uses_amh_before_npx(self, tmp_path, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}" if name in {"amh", "npx"} else None)

        payload = memory_status_payload(
            workspace=tmp_path,
            namespace="project:test",
            memory_backend="amh",
            memory_amh_store="sqlite",
        )

        assert payload["ok"] is True
        assert payload["amh"]["command"] == ["amh"]
        assert payload["amh"]["using_npx_fallback"] is False
        assert payload["amh"]["path"].endswith(".agentx/amh/memory.db")

    def test_memory_status_payload_live_probe(self, tmp_path, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/amh" if name == "amh" else None)

        def fake_run(cmd, capture_output=True, timeout=None, check=False):
            class Result:
                returncode = 0
                stdout = b"Usage: amh"
                stderr = b""

            return Result()

        monkeypatch.setattr("subprocess.run", fake_run)

        payload = memory_status_payload(
            workspace=tmp_path,
            namespace="project:test",
            memory_backend="amh",
            live_probe=True,
        )

        assert payload["ok"] is True
        assert payload["live_probe"] is True
        assert payload["amh"]["live_probe_result"]["ok"] is True
        assert payload["amh"]["live_probe_result"]["command"] == "amh --help"


class TestMemoryReadWritePayload:
    def test_memory_read_payload_searches_backend(self):
        memory = MagicMock()
        memory.search.return_value = "result line"

        payload = memory_read_payload(
            memory=memory,
            query="handoff",
            namespace="project:test",
            limit=3,
        )

        assert payload["schema"] == "agentx.memory_read.v1"
        assert payload["ok"] is True
        assert payload["result"] == "result line"
        memory.search.assert_called_once_with("handoff", namespace="project:test", limit=3)

    def test_memory_read_payload_blocks_empty_query(self):
        memory = MagicMock()

        payload = memory_read_payload(memory=memory, query=" ", namespace="project:test")

        assert payload["ok"] is False
        assert payload["blockers"] == ["query_required"]
        memory.search.assert_not_called()

    def test_memory_write_payload_dry_run_does_not_write(self):
        memory = MagicMock()

        payload = memory_write_payload(
            memory=memory,
            content="preview this",
            namespace="project:test",
            memory_type="handoff",
        )

        assert payload["schema"] == "agentx.memory_write.v1"
        assert payload["ok"] is True
        assert payload["write"] is False
        assert payload["warnings"] == ["dry_run_no_memory_written"]
        assert payload["recommended_kind"] == "memory_write_execute"
        memory.write_aca.assert_not_called()

    def test_memory_write_payload_write_calls_aca_backend(self):
        memory = MagicMock()
        memory.write_aca.return_value = {"memory_id": "mem-1"}

        payload = memory_write_payload(
            memory=memory,
            content="write this",
            namespace="project:test",
            memory_type="fact",
            tier="human_confirmed",
            write=True,
        )

        assert payload["ok"] is True
        assert payload["memory_result"] == {"memory_id": "mem-1"}
        memory.write_aca.assert_called_once_with(
            content="write this",
            namespace="project:test",
            memory_type="fact",
            source_tier="human_confirmed",
        )

    def test_memory_write_payload_blocks_invalid_type_and_tier(self):
        memory = MagicMock()

        payload = memory_write_payload(
            memory=memory,
            content="bad",
            namespace="project:test",
            memory_type="weird",
            tier="bad",
            write=True,
        )

        assert payload["ok"] is False
        assert payload["blockers"] == ["invalid_tier", "invalid_memory_type"]
        memory.write_aca.assert_not_called()
