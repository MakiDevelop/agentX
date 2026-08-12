"""Token accounting for the context budget.

agentX decides when to compact from a token estimate. That estimate used to be
``len(text) // 4`` — the rule of thumb for English text, applied to a tool whose
prompts, personas, user requests and answers are largely Traditional Chinese.

Measured on realistic agentX conversation content (52% CJK), ``chars // 4``
reports 994 tokens where any real tokenizer must produce at least 2539 — a 2.6x
under-count. The consequence is not a cosmetic number: `_maybe_auto_compact`
fires at 82% of `context_limit_tokens`, so under-counting by 2.6x means
compaction triggers only after the real context has already blown past the
limit. The mechanism meant to prevent overflow was itself mistimed by it.

Two corrections live here:

1. `estimate_tokens` is character-class aware. CJK ideographs are counted at
   roughly one token each; Latin text keeps the ~4-chars-per-token ratio.

2. `TokenCounter` accepts ground truth. Ollama returns `prompt_eval_count` on
   every response — the tokenizer's own count for the exact prompt we sent.
   Feeding that back lets the estimator calibrate to whatever model is loaded
   instead of guessing on its behalf.

**A budget must err high.** Over-estimating compacts a little early, which costs
some context. Under-estimating overflows the model's window, which ends the run.
The defaults here are deliberately on the conservative side of measured ratios.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Ranges where one character is worth roughly one token. Covers CJK ideographs,
#: kana, Hangul and full-width forms — everything a byte-pair tokenizer trained
#: mostly on Latin script does not compress well.
_DENSE_RANGES: tuple[tuple[int, int], ...] = (
    (0x3040, 0x30FF),  # hiragana + katakana
    (0x3400, 0x4DBF),  # CJK ext A
    (0x4E00, 0x9FFF),  # CJK unified ideographs
    (0xF900, 0xFAFF),  # CJK compatibility ideographs
    (0xFF00, 0xFFEF),  # full-width forms
    (0xAC00, 0xD7AF),  # Hangul syllables
    (0x20000, 0x2FA1F),  # CJK ext B-F
)

#: Tokens per character for dense (CJK-like) script. Real tokenizers land around
#: 0.6-1.2 depending on the model's merges; 1.0 is the conservative middle.
DENSE_TOKENS_PER_CHAR = 1.0

#: Characters per token for everything else — the familiar English heuristic.
SPARSE_CHARS_PER_TOKEN = 4.0

#: Per-message overhead (role markers, delimiters) charged by chat APIs.
MESSAGE_OVERHEAD_TOKENS = 4


def _is_dense(codepoint: int) -> bool:
    return any(low <= codepoint <= high for low, high in _DENSE_RANGES)


def count_dense_chars(text: str) -> int:
    """Number of characters that tokenize at roughly one token each."""
    return sum(1 for char in text if _is_dense(ord(char)))


def estimate_tokens(text: str) -> int:
    """Estimate tokens for a string, accounting for script density.

    Not exact — no tokenizer is loaded, deliberately, so the estimate works
    offline and for whichever local model is configured. It is designed to never
    be wildly *low*, which is the direction that breaks a run.
    """
    if not text:
        return 0
    dense = count_dense_chars(text)
    sparse = len(text) - dense
    return int(dense * DENSE_TOKENS_PER_CHAR + sparse / SPARSE_CHARS_PER_TOKEN)


def estimate_messages_tokens(messages: list[dict[str, str]]) -> int:
    """Estimate tokens for a chat message list, including per-message overhead."""
    total = 0
    for message in messages:
        total += estimate_tokens(str(message.get("content", "")))
        total += estimate_tokens(str(message.get("role", "")))
        total += MESSAGE_OVERHEAD_TOKENS
    return total


@dataclass
class TokenCounter:
    """Estimator that calibrates against counts reported by the model.

    Ollama returns `prompt_eval_count` — the number of tokens the model's own
    tokenizer produced for the prompt we just sent. That is ground truth, free,
    and was previously discarded. `observe()` feeds it back so the running
    correction factor reflects the model actually loaded.
    """

    #: Multiplier applied to raw estimates. Starts neutral and moves toward the
    #: observed ratio as real counts arrive.
    calibration: float = 1.0
    #: How much each observation moves the calibration. Low enough that one
    #: unusual turn cannot swing the budget.
    smoothing: float = 0.25
    observations: int = 0
    _history: list[tuple[int, int]] = field(default_factory=list)

    #: Never trust an observation to move calibration outside this band; a wild
    #: value usually means the prompt we measured is not the prompt that was sent.
    MIN_CALIBRATION = 0.25
    MAX_CALIBRATION = 4.0

    def estimate(self, text: str) -> int:
        return max(0, int(estimate_tokens(text) * self.calibration))

    def estimate_messages(self, messages: list[dict[str, str]]) -> int:
        return max(0, int(estimate_messages_tokens(messages) * self.calibration))

    def observe(self, messages: list[dict[str, str]], actual_tokens: int) -> None:
        """Record a real token count for a prompt we estimated.

        Ignores non-positive counts: backends that do not report usage return 0,
        and treating that as "the prompt was free" would drive calibration to
        zero and disable compaction entirely.
        """
        if actual_tokens <= 0:
            return
        raw = estimate_messages_tokens(messages)
        if raw <= 0:
            return
        self._history.append((raw, actual_tokens))
        ratio = actual_tokens / raw
        blended = (1 - self.smoothing) * self.calibration + self.smoothing * ratio
        self.calibration = min(self.MAX_CALIBRATION, max(self.MIN_CALIBRATION, blended))
        self.observations += 1

    def report(self) -> dict[str, float | int]:
        return {
            "calibration": round(self.calibration, 3),
            "observations": self.observations,
        }
