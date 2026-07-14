# agentX — NEXT SESSION（2026-06 更新）

> 本檔 = 從哪裡接續的指標（committed 版本，供 repo 內所有人參考）。完整脈絡見 AGENTX.md（尤其是 Appendix 借鏡 ai-tetsu） + docs/ 指南 + 各人本機 .agentx/handoff/（local，不進 git）。

## 核心原則（RATIFIED，參考 ai-tetsu + CLAUDE.md 精神）
**agentX 的 kernel = 把「可靠本地工程 agent shell」的能力矩陣實體化。**
- 每個 kernel 器官對應一條能力 row（bootstrap/context、ToolRegistry、Execution Loop、Task Truth、Reliability Gates、Memory、Self-Improvement）。
- Substrate（LLM via mk-council/ollama、MemoryHall、RAG）= 外接可換模組，**kernel 不得 import substrate**，一律 injection。
- 持久化以 .agentx/ 為 md source-of-truth + grep + explicit archive forgetting。
- AGENTX.md 是活的專案憲法 + 自修改協議（proposal + gate + fitness for core changes）。
- Fidelity：量「當前實作是否仍忠於 AGENTX.md 原則」（壓力不變式 vs 狀態相依），用 probe 追蹤 drift。

（完整細節見 AGENTX.md Appendix: Inspiration from ai-tetsu）

## 現狀（post MT22 merge + AGENTX.md v1 + ai-tetsu 借鏡）
- MT22 Phase A 完成：tasks.py 為唯一真相，legacy task.py 已移除，自動遷移 + doctor 診斷保留。
- AGENTX.md 已依 ~/.claude/CLAUDE.md 結構重新設計（v1），並新增 ai-tetsu Appendix（kernel blueprint、proposal-only self-mod、fidelity constitution、rules layer、NEXT_SESSION 風格）。
- bootstrap.py 已更新：優先載入 AGENTX.md，並自動載入 .agentx/handoff/ 的 NEXT_SESSION.md / CONVERSATION_HANDOFF.md（ai-tetsu 風格；若本機有 local 版本會優先）。
- Headless 可靠性、工具註冊、AgentSession/Coordinator/Orchestrator 為 kernel 核心器官。
- .agentx/ 作為專案記憶（config、tasks.json、handoff、sessions）。
- 自修改協議已寫死：允許學習後修改 AGENTX.md（帶 gate 與驗證）。

## 下一步 / 接續點
1. fidelity probe：已補 deterministic v0（檢查 AGENTX.md、MT22 真相、bootstrap、learning gate、no-legacy pre-commit）；後續再強化 ai-tetsu fidelity-question-bank + constitution。
2. 將 rules layer（確定性 guardrail，如 ruff + no-legacy + AGENTX.md 一致性檢查）整合進開發流程 / CI / pre-commit。
3. learning / 自改進提案：已補 proposal status gate（proposed/under_review/approved/applied/rejected，applied 必須記 applied_to）；後續再補人工核准後寫 AGENTX.md / handoff 的操作面。
4. 更新本檔（或本機 .agentx/handoff/NEXT_SESSION.md）當有新 RATIFIED 決策（從 Codex/Grok Build/Gemini council 或人類）。
5. 借鏡 ai-tetsu：考慮在 .agentx/ 引入更明確的 episodes/ + proposals/ 子結構（md source-of-truth）。
6. 測試 bootstrap 載入 AGENTX.md + handoff 的端到端（在 shell/ask 啟動時）。
7. 當有重大 kernel 改動時，更新 AGENTX.md 的 kernel 器官定義，並跑 fidelity probe。

**Maki 提醒（升格為原則）**：像 ai-tetsu 一樣，「人性善變——威逼利誘下，基準本身會動。」所以 AGENTX.md 的壓力不變式原則（安全、MT22 真相、kernel/substrate 分離、自修改紀律）需定期人工重確認；其他可依狀態調整。模型/實作的價值在於量「說的」與「壓力下的」差距。

**Evidence**：本 session + 之前 MT22 merge + ai-tetsu 專案結構（kernel-blueprint, NEXT_SESSION, rules.py, persona-constitution, fidelity-probe 等）。

下一步從讀 AGENTX.md（含 Appendix） + 本機 .agentx/handoff/NEXT_SESSION.md（如果存在） + `agentx doctor` 開始。

（本檔為 committed 範本；實際執行時的活文件建議放在 .agentx/handoff/NEXT_SESSION.md，本地 gitignored。）

## 新增：自我學習機制 (2026-06)
- 自動觸發：在 ask() 成功 final answer 後 (非 plan mode)，如果 learning_enabled，自動呼叫 reflect_and_learn() 產生 proposals。
- 也在 max_steps 結束的 incomplete session 時嘗試學習（從「失敗」中學）。
- 手動：/learn slash command 隨時強制 reflection。
- proposals 寫到 .agentx/learning/proposals/ (md + json)，proposal-only，永不自動 apply 到核心 (AGENTX.md 等)。
- 整合 recovery、memory、prompts。
- 符合 AGENTX.md 自修改協議 + ai-tetsu proposal gate + fidelity。
- 讓 agentX 越用越「聰明」：學 recovery 策略、prompt 改善、任務模式、甚至建議更新 AGENTX.md。
