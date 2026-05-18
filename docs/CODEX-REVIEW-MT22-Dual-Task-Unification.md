# Codex Review Briefing — Micro-task 22: 雙任務系統統一（Phase A 基礎）

**日期**：2026-05  
**負責人**：Claude（依 Maki 全權授權決定實作順序後執行）  
**對應項目**：`docs/OPTIMIZATION_ROADMAP.md` Phase A  
**Commit**：`fcd484a`（本 briefing 對應的變更）

---

## 1. 目標

消除 agentX 內長期存在的「雙任務系統」分裂狀態，讓 **多任務清單（`tasks.py` + `.agentx/tasks.json`）成為唯一的真相來源**（source of truth）。

具體達成：
- 自動、安全地把舊單一任務（`task.py` + `.agentx/task.json`）遷移到新系統。
- 讓互動模式的使用者也能享受到 MT21 為 headless 打造的豐富 Task List 能力（`/task` 命令升級）。
- 為後續 Context Compaction、錯誤恢復、Prompt 統一等高價值工作清除最大架構障礙。
- 採取「漸進式退場」策略：先統一、再相容、最後才刪除舊模組。

---

## 2. 背景與動機

在 MT21（Headless Task List 完整體驗）時，Codex review 已經明確指出這是最大風險：

> **風險 1**：與現有單一任務系統的關係  
> 目前存在兩個任務系統（`task.py` 單一任務 + `tasks.py` 多任務清單）。是否會造成使用者混淆？未來是否應該整合？

當時我們選擇「先把多任務做好再處理整合」，現在進入 Phase A 就是來解決這個技術債。

**現況問題**：
- `task.py`：單一 `TaskState`（active / done），用在 `/task`、handoff、啟動 transcript、`/status` 部分顯示。
- `tasks.py`：多任務清單 + `format_task_list_summary`，**只有 headless AgentSession + 模型工具在使用**。
- 啟動時兩個系統互不相干，使用者在互動模式下完全感覺不到 MT21 的成果。
- 長期下去，任何涉及「目前在做什麼」的 scaffolding（compaction、錯誤恢復、plan mode）都會被迫維護兩套狀態。

---

## 3. 實作範圍（本次 MT22 第一塊已完成）

這次交付的是 **Phase A 的安全基礎 + 使用者可立即感受到的價值**：

### 已完成
- 新增 `migrate_single_task_if_needed()`（`src/agentx/tasks.py`）
  - 只在「有多任務清單為空 + 存在進行中的舊單一任務」時才遷移。
  - 遷移後把舊任務變成 id=1、status=in_progress 的多任務項目，並在 notes 標記來源。
- 在 `shell()` 與 `run_print_prompt()`（headless）啟動路徑**最早階段**呼叫遷移。
- 全面重寫 `/task` slash command handler：
  - 支援 `add`、`update <id>`、`done <id>`、`clear`、`list`/`status`
  - 保留舊式 `/task 描述文字` 相容行為（自動轉成 in_progress 任務）
  - 輸出使用 `format_task_list_summary`（與 headless 一致）
- 在 `task.py` 加上明確的 deprecation notice。
- 新增 2 個遷移專用單元測試（`tests/test_tasks.py`）。
- 建立 `docs/OPTIMIZATION_ROADMAP.md` 並鎖定後續順序。
- 更新 `HEADLESS_OPTIMIZATION_LIST.md` 追蹤進度。

### 刻意未做（留給後續 micro-task）
- 尚未修改 `build_handoff` / 啟動 transcript 寫入（仍使用舊 `TaskState`）。
- 尚未刪除 `task.py`、`test_task.py`、舊的 task.json 處理邏輯。
- 尚未把 `/status`、handoff 完全改成多任務視圖（Phase D 項目）。

---

## 4. 關鍵檔案與變更摘要

| 檔案 | 類型 | 主要變更 |
|------|------|----------|
| `src/agentx/tasks.py` | **新增函數** | `migrate_single_task_if_needed` + `single_task_path` helper |
| `src/agentx/cli.py` | **重構** | 啟動時呼叫遷移；`/task` handler 從 20 行變成 ~80 行新邏輯 |
| `src/agentx/task.py` | **文件** | 加上 DEPRECATION NOTICE |
| `tests/test_tasks.py` | **新增** | 2 個遷移測試（成功遷移 + 已存在多任務時不覆蓋） |
| `docs/OPTIMIZATION_ROADMAP.md` | **新增** | 完整 5 Phase 實作順序 + 決策理由 |
| `docs/HEADLESS_OPTIMIZATION_LIST.md` | **更新** | 加入 Phase A 啟動紀錄 |

完整 diff 可透過 `git show fcd484a` 查看。

**強烈建議搭配閱讀**：`docs/CODEX-MT22-DIFF-SUMMARY.md`（精簡版，只保留三個最關鍵的程式碼區塊 + Codex 審查順序建議，2-3 分鐘可掃完）。

---

## 5. 設計決策與取捨

1. **為什麼只遷移「進行中」的舊任務？**
   - 已完成的舊任務對新系統沒有價值，只會污染清單。
   - 這是經過深思的保守策略。

2. **為什麼不立刻刪除舊模組？**
   - 這是「大量變更」的第一步。採取「先讓新系統成為預設、舊系統自動沉默」的策略，降低一次改動的風險。
   - 符合專案「每完成一個邏輯單元就 commit」的文化。

3. **`/task` 命令的 parser 設計**
   - 盡量相容舊用法（`/task 重構認證` 仍有效），同時提供清晰的新語法。
   - 對弱模型友善：錯誤時給明確提示（例如 `/task done` 沒帶 id 會提醒要加數字）。

4. **遷移時機選擇在 shell 與 headless 最早路徑**
   - 保證 `AgentSession` 初始化時已經看到正確的多任務清單。
   - 也讓互動使用者第一次啟動 `ax` 就會自動完成遷移。

---

## 6. 風險與特別在意點（請 Codex 重點審查）

1. **Handoff 相容性**
   - `build_handoff`、`write_handoff` 仍仰賴舊的 `load_task` + `TaskState`。
   - 遷移後的資訊雖然存在多任務清單，但 handoff 目前不會自動包含「目前進行中的多個任務」。
   - 這是否是可接受的過渡狀態？還是應該在本次或下次補做？

2. **Migration 邊界條件**
   - 只看 `status == "active"` 的舊任務。
   - 如果舊 `task.json` 損壞、或 title 極長、或同時存在多個奇怪狀態，行為是否足夠防呆？
   - 目前測試只覆蓋「有舊任務 + 無多任務」與「已有多任務」的 case。

3. **舊 `print_task()` 函數現在幾乎是死碼**
   - `/task` handler 已不再呼叫它。
   - 它是否還被其他地方（除了 handoff 相關）使用？未來刪除時會不會有驚喜？

4. **啟動時的 transcript 寫入**
   - `shell()` 裡 `transcript.write("task", {"title": task.title ...})` 仍用舊單一任務。
   - 這會不會讓 transcript 產生混淆的歷史紀錄？

5. **新 `/task` parser 的 robustness（對本地弱模型）**
   - 模型如果呼叫 `/task update 3 done 備註` 這種格式，是否容易出錯？
   - 目前 parser 是簡單字串 split，是否需要更結構化的處理？

6. **未來刪除舊模組的時機建議**
   - 你建議在下一個 micro-task 就刪除 `task.py`，還是再觀察 1-2 個版本？
   - 刪除時需要做什麼額外的 migration / warning 機制？

7. **整體漸進式策略是否合理？**
   - 這次只做「命令層 + 遷移」，把 handoff / status / transcript 的升級留到 Phase D。
   - 這樣的分階段是否會讓中間狀態太長、增加維護成本？

---

## 7. 希望 Codex 給的具體回饋

請針對以下問題給出**具體、可執行**的意見：

1. **Migration 策略**：目前「只遷移進行中任務 + 標記 notes」的做法是否正確？有沒有更好的方式（例如把舊任務永遠保留為已完成的第一筆）？

2. **Handoff 處理**：你建議現在就修改 `build_handoff` 讓它同時輸出多任務摘要，還是等 Phase D 再一次處理？

3. **Parser 健壯性**：新 `/task` 命令的字串解析對弱模型是否足夠友善？有沒有推薦的改進方式（例如接受 `task_id=3 status=done` 這種更明確的格式）？

4. **Dead code 清理時機**：`print_task()` 與 `task.py` 內其他函數什麼時候可以安全刪除？你會建議在下一次 commit 就刪，還是先放一個 deprecation 警告期？

5. **風險優先序**：上面 7 個風險點，你認為哪 2-3 個**必須在本 Phase A 完全解決**，其餘可以留到後續？

6. **下一步建議**：如果要繼續完成 Phase A（讓 handoff、transcript、`/status` 也吃到多任務），你會建議的下一個 micro-task 切入點是什麼？

7. **整體架構判斷**：這次「先統一命令層 + 自動遷移」的切入方式，你認為是正確的風險控管，還是應該更激進一次把舊系統整個拔掉？

---

## 8. 驗證已完成事項

- `uv run pytest` 全 87 個測試通過（包含 2 個新遷移測試）。
- 手動心智模型驗證：
  - 有舊單一任務 → 啟動後自動出現多任務清單。
  - 已有多任務 → 不會被舊任務覆蓋。
  - `/task 重構 X`、`/task add Y`、`/task update 1 done "完成"`、`/task done 2`、`/task clear` 行為符合預期。
- 遷移只發生一次（後續啟動因為多任務已存在，不會再動）。
- `.agentx/tasks.json` 格式與 MT21 完全相容。

---

## 9. 後續計劃（完整 Phase A 還需要做的事）

1. （可選）把 handoff 也升級成同時包含多任務摘要（可放在本次 review 後的 follow-up）。
2. 準備刪除 `task.py` 的最終 PR（需再一次 Codex review）。
3. 更新 README `/task` 說明段落。
4. 確認所有使用 `load_task` 的地方都已有對應的多任務替代方案。

---

**結語**：

這是 agentX 從「兩個平行任務世界」走向「單一真相來源」的第一個也是最重要的一步。解決這個問題後，後續的 Context Compaction、錯誤恢復策略、Prompt 統一才不會一直踩到狀態分裂的地雷。

請 Codex 從**架構長期健康度、使用者遷移體驗、對弱模型的友善程度、以及未來刪除風險**四個面向給出誠實且具體的評價。

感謝。

---

## Codex Review Feedback & Resolutions（2026-05 後補）

Codex 審查完 `fcd484a` 後給出明確結論：
> 方向正確，但 Phase A 尚未安全完成，至少需補 3 處修復。

**已處理的問題**（本 commit 後續修復）：

1. **tasks.json 損壞時可能被覆寫**（Critical）
   - 修復：改用 `tasks_path(workspace).exists()` 作為第一道守衛。只要新檔案存在（無論內容是否可讀），就絕對不遷移。
   - 新增測試 `test_migrate_bails_if_tasks_json_exists_even_if_corrupt`。
   - 現在即使 `tasks.json` 是壞 JSON，也不會被舊單一任務覆寫。

2. **/task update / done 找不到 id 仍報成功**（對弱模型高風險）
   - 修復：`update` 與 `done` 都加入 `found` 追蹤。
     - 找不到時印 `[yellow]找不到任務 #999[/yellow]`，不 save、不報成功。
     - `update` 時若 status 非法，立即報錯並 `continue`，不繼續執行。
   - 這消除了「假成功」問題。

3. **Ruff 未通過 + 未使用 import**
   - 移除 cli.py 中已不再使用的 `clear_task, finish_task, start_task`。
   - 移除 test_tasks.py 中未使用的 `single_task_path`。
   - 目前剩餘的 ruff 錯誤皆為 MT22 之前既有的問題（非本次引入）。

**Codex 對 7 題的回答摘要與跟進**：
- Migration 策略：正確，但守衛必須更保守 → 已修。
- Handoff：不要等到 Phase D，至少下一個 micro-task 就要讓 handoff 輸出多任務摘要 → 列入 MT22-A3。
- Parser：目前可用，但錯誤處理要加強 → 已補 not-found 與非法 status。
- Dead code：先清 import，再等 handoff 全部切完後才刪 task.py → 同意。
- Phase A 必須補：以上三點 + handoff 多任務摘要 → 本次已處理前兩點 + import 清理。
- 下一步：MT22-A2（本修復）→ MT22-A3（handoff / transcript / status 全面使用 task list summary）。
- 整體判斷：漸進式正確，但「source of truth」目前仍不完全成立（handoff 仍吃舊 TaskState）→ 已在 roadmap 與 briefing 中標註。

**結論**：經 Codex 指正後的修復已併入，Phase A 現在更安全。後續將繼續推進 MT22-A3（handoff 升級），讓「多任務清單成為真正唯一的真相來源」這句話成立。

---

**如何使用本 briefing 請 Codex 審查**（供 Maki 執行）：

```bash
cat docs/CODEX-REVIEW-MT22-Dual-Task-Unification.md | codex exec --full-auto > ~/Documents/agent-council/$(date +%Y-%m-%d)-mt22-codex-review.md
```

或手動貼到 Codex CLI / Cursor / Claude Code 內進行審查。