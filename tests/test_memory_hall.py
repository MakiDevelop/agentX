from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agentx.memory_hall import (
    ACA_MEMORY_TYPES,
    ACA_SOURCE_TIERS,
    MemoryHallClient,
)
from agentx.tools.builtin import MemoryWriteTool


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