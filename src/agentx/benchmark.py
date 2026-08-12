"""Measure how reliably a local model can actually drive agentX.

The existing reliability suite replays *recorded* cases: it proves the runner
mechanics work, but says nothing about whether gemma4 or qwen3.6 can hold up the
protocol on a real turn. Without that number, every prompt or loop change is
judged by impression.

What this measures, per model:

- **JSON compliance** — fraction of turns that parsed into a valid action.
  agentX's whole protocol rests on "exactly one JSON object per turn"; a weak
  model that emits prose 30% of the time is the single biggest reliability drag.
- **Action validity** — of the turns that parsed, how many named a real tool
  with plausible arguments. A syntactically perfect call to a tool that does not
  exist is still a wasted turn.
- **Recovery** — after an invalid turn is rejected, does the next turn parse?
  A model that cannot recover from correction turns one bad turn into a stall.

Deliberately *not* a pass/fail gate. It is an instrument: run it before and
after a prompt change and compare. Numbers from different models or different
prompt versions are only comparable when the case set and the seed prompt are
identical, which is why both are pinned here rather than passed in ad hoc.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from agentx.json_repair import extract_json_object
from agentx.protocol import FinalAnswer, Reflect, ToolCall

BENCHMARK_SCHEMA = "agentx.local_model_benchmark.v1"


def _ratio(numerator: int, denominator: int) -> float | None:
    """None, not 0.0, when nothing was measured — they mean different things."""
    if denominator <= 0:
        return None
    return round(numerator / denominator, 3)


@dataclass(frozen=True)
class BenchmarkCase:
    """One turn put to the model, with what a correct answer looks like."""

    name: str
    prompt: str
    #: Action type a competent answer would use.
    expects_type: str
    #: Tool a competent answer would call, when expects_type is "tool_call".
    expects_tool: str | None = None


#: Pinned case set. Changing these invalidates comparison with earlier runs, so
#: add cases rather than editing them, and note the change in the report.
BENCHMARK_CASES: tuple[BenchmarkCase, ...] = (
    BenchmarkCase(
        name="list_workspace",
        prompt="列出 workspace 根目錄有哪些檔案。",
        expects_type="tool_call",
        expects_tool="list_files",
    ),
    BenchmarkCase(
        name="read_named_file",
        prompt="讀取 README.md 的內容。",
        expects_type="tool_call",
        expects_tool="read_file",
    ),
    BenchmarkCase(
        name="search_repo",
        prompt="在這個 repo 裡搜尋 approval 這個關鍵字出現在哪些檔案。",
        expects_type="tool_call",
        expects_tool=None,
    ),
    BenchmarkCase(
        name="create_new_file",
        prompt="建立一個新檔案 notes.txt，內容是 hello。",
        expects_type="tool_call",
        expects_tool="write_file",
    ),
    BenchmarkCase(
        name="answer_without_tools",
        prompt="用一句話說明你現在能做什麼。不要呼叫任何工具，直接給最終答案。",
        expects_type="final",
        expects_tool=None,
    ),
    BenchmarkCase(
        name="git_state",
        prompt="這個 repo 現在的 git 狀態是什麼？",
        expects_type="tool_call",
        expects_tool="git_status",
    ),
    # --- Cases below exercise tools the old hand-written prompt never taught.
    # The first six cases turned out not to discriminate: gemma4:31b picked the
    # right tool even from a prompt that omitted it, because the names are
    # guessable. These are the tools whose *existence* the model cannot infer.
    BenchmarkCase(
        name="docker_compose_state",
        prompt="看一下這個專案的 docker compose 目前有哪些服務在跑。",
        expects_type="tool_call",
        expects_tool="docker_compose_ps",
    ),
    BenchmarkCase(
        name="fetch_external_url",
        prompt="幫我抓 https://example.com 這一頁的內容來看。",
        expects_type="tool_call",
        expects_tool="web_fetch",
    ),
    BenchmarkCase(
        name="edit_existing_file",
        prompt="把 README.md 裡的 'agentX' 這個字改成 'AgentX'，只改這一處。",
        expects_type="tool_call",
        expects_tool="edit_file",
    ),
    # Known soft cases: gemma4:31b answers these with `list_files` / `read_file`
    # under both prompts. Those are defensible answers (list_files genuinely
    # does what `ls -la` does; reading before editing is good practice), so a
    # miss here is weaker evidence than a miss above. Kept because they are
    # where a stricter model should pull ahead.
    BenchmarkCase(
        name="run_allowlisted_command",
        prompt="執行 ls -la 看看目錄內容。",
        expects_type="tool_call",
        expects_tool="run_command",
    ),
    BenchmarkCase(
        name="memory_lookup",
        prompt="查一下 Memory Hall 裡有沒有關於 approval policy 的記憶。",
        expects_type="tool_call",
        expects_tool="memory_search",
    ),
)

#: Sent after an unparseable turn, mirroring what the real loop does.
CORRECTION_PROMPT = (
    "Invalid response. Return strict JSON only, exactly one object. "
    'To use a tool: {"type":"tool_call","tool":"<name>","args":{...}}. '
    'To finish: {"type":"final","content":"..."}'
)


@dataclass
class TurnOutcome:
    case: str
    raw: str
    parsed: bool
    #: Parsed only after json_repair had to intervene.
    needed_repair: bool
    action_type: str | None
    tool: str | None
    tool_exists: bool
    matched_expectation: bool
    recovered_after_correction: bool | None
    latency_seconds: float


@dataclass
class BenchmarkReport:
    model: str
    backend: str
    base_url: str
    outcomes: list[TurnOutcome] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def _rate(self, predicate: Any) -> float:
        if not self.outcomes:
            return 0.0
        return sum(1 for o in self.outcomes if predicate(o)) / len(self.outcomes)

    def payload(self) -> dict[str, Any]:
        recoveries = [o for o in self.outcomes if o.recovered_after_correction is not None]
        return {
            "schema": BENCHMARK_SCHEMA,
            "model": self.model,
            "backend": self.backend,
            "base_url": self.base_url,
            "case_count": len(self.outcomes),
            "metrics": {
                # The protocol's floor: did the turn parse into an action at all.
                "json_compliance": round(self._rate(lambda o: o.parsed), 3),
                # Parsed only because json_repair rescued it — a leading
                # indicator that raw compliance is worse than it looks.
                "needed_repair": round(self._rate(lambda o: o.needed_repair), 3),
                # Of the turns that named a tool, how many named a real one.
                # Measured only over tool-calling turns: a "final" answer names
                # no tool, and counting that as a miss would penalise the model
                # for correctly declining to use one.
                "tool_exists": _ratio(
                    sum(1 for o in self.outcomes if o.tool and o.tool_exists),
                    sum(1 for o in self.outcomes if o.tool),
                ),
                # Did what the case actually called for.
                "expectation_match": round(self._rate(lambda o: o.matched_expectation), 3),
                # Of the turns that failed, how many recovered when corrected.
                "recovery_after_correction": (
                    round(
                        sum(1 for o in recoveries if o.recovered_after_correction)
                        / len(recoveries),
                        3,
                    )
                    if recoveries
                    else None
                ),
                "mean_latency_seconds": (
                    round(sum(o.latency_seconds for o in self.outcomes) / len(self.outcomes), 2)
                    if self.outcomes
                    else 0.0
                ),
            },
            "cases": [
                {
                    "case": o.case,
                    "parsed": o.parsed,
                    "needed_repair": o.needed_repair,
                    "action_type": o.action_type,
                    "tool": o.tool,
                    "tool_exists": o.tool_exists,
                    "matched_expectation": o.matched_expectation,
                    "recovered_after_correction": o.recovered_after_correction,
                    "latency_seconds": round(o.latency_seconds, 2),
                    # Truncated: enough to see what went wrong without dumping
                    # a whole model response into a report.
                    "raw_excerpt": o.raw[:300],
                }
                for o in self.outcomes
            ],
            "notes": self.notes,
        }


def _parse_action(raw: str) -> tuple[dict[str, Any] | None, bool]:
    """Return (validated action, needed_repair).

    Deliberately the *same* path AgentSession._parse_action takes:
    `extract_json_object` followed by pydantic validation. A benchmark that
    parsed more leniently than the loop would report compliance the loop cannot
    actually use; one that parsed more strictly would understate the model.

    `needed_repair` is True when the raw text was not valid JSON on its own and
    only became usable after extraction — a leading indicator that raw
    compliance is worse than the headline number suggests.
    """
    strict_ok = True
    try:
        json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        strict_ok = False

    data = extract_json_object(raw)
    if data is None:
        return None, not strict_ok

    try:
        if data.get("type") == "tool_call":
            ToolCall.model_validate(data)
        elif data.get("type") == "reflect":
            Reflect.model_validate(data)
        else:
            FinalAnswer.model_validate(data)
    except (AttributeError, ValidationError):
        # Parsed as JSON but not a valid action — the loop would reject it too.
        return None, not strict_ok

    return data, not strict_ok


def run_benchmark(
    client: Any,
    system_prompt: str,
    known_tools: set[str],
    *,
    model: str,
    backend: str = "ollama",
    base_url: str = "",
    cases: tuple[BenchmarkCase, ...] = BENCHMARK_CASES,
) -> BenchmarkReport:
    """Put each case to the model as a fresh single turn.

    A fresh conversation per case: the point is to measure the model's behaviour on the protocol,
    not to let a good first turn carry a weak one. Any per-case failure is
    recorded and the run continues — a benchmark that aborts on the first bad
    turn cannot measure how bad things are.
    """
    report = BenchmarkReport(model=model, backend=backend, base_url=base_url)

    for case in cases:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": case.prompt},
        ]
        started = time.monotonic()
        try:
            raw = client.chat(messages, json_mode=True)
        except Exception as exc:  # noqa: BLE001 - a dead backend is a datapoint
            report.outcomes.append(
                TurnOutcome(
                    case=case.name,
                    raw=f"{type(exc).__name__}: {exc}",
                    parsed=False,
                    needed_repair=False,
                    action_type=None,
                    tool=None,
                    tool_exists=False,
                    matched_expectation=False,
                    recovered_after_correction=None,
                    latency_seconds=time.monotonic() - started,
                )
            )
            report.notes.append(f"{case.name}: backend error {type(exc).__name__}")
            continue

        latency = time.monotonic() - started
        action, needed_repair = _parse_action(raw)
        parsed = action is not None
        action_type = str(action.get("type")) if parsed else None
        tool = str(action.get("tool")) if parsed and action.get("tool") else None
        tool_exists = bool(tool and tool in known_tools)

        matched = bool(
            parsed
            and action_type == case.expects_type
            and (case.expects_tool is None or tool == case.expects_tool)
        )

        recovered: bool | None = None
        if not parsed:
            # Same correction the real loop sends. Measures whether one bad turn
            # becomes a stall.
            retry_messages = [
                *messages,
                {"role": "assistant", "content": raw},
                {"role": "user", "content": CORRECTION_PROMPT},
            ]
            try:
                retry_raw = client.chat(retry_messages, json_mode=True)
                retry_action, _ = _parse_action(retry_raw)
                recovered = retry_action is not None
            except Exception:  # noqa: BLE001
                recovered = False

        report.outcomes.append(
            TurnOutcome(
                case=case.name,
                raw=raw,
                parsed=parsed,
                needed_repair=needed_repair and parsed,
                action_type=action_type,
                tool=tool,
                tool_exists=tool_exists,
                matched_expectation=matched,
                recovered_after_correction=recovered,
                latency_seconds=latency,
            )
        )

    return report
