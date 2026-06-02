# 2026-06-02 terminal-crash-file-integrity

> 個人專案 / Terminal crash 後檔案完整性驗證 + web helpers post-merge wiring / Outcome: ruff clean + 3 tests pass on real code, no data loss

## 觸發點
Terminal.app 於 2026-06-02 18:49 大當機（ips report 確認）。使用者要求檢查影響 + 做收尾。

## Root cause / 動作 / 修法
- Crash 本身 isolated to Terminal（系統 uptime 19d，無 reboot）。
- 檢查 git / fsck / locks / recent mtime / processes / history / crash logs：**無 code 或 repo 損壞**。
- 發現進行中的 change：src/agentx/tools/_helpers.py 新增 web helpers（extract_web_text + validate_external_url，用於 Gemma-friendly web 工具 + test_tools）。
- 完整性 gap：helpers 未 export（__init__.py）、tests 仍用 temp stubs + 錯誤 monkeypatch 路徑（無法測試真實邏輯）、ruff E402（imports 不在頂部）。
- 動作：hoist imports、更新 __init__ exports、清理 test stubs 並修正 patch target、re-verify。
- web_fetch tool 實作仍缺失（cli /fetch 與 safety 有呼叫）→ 記錄為 follow-up。

## 改動清單
- src/agentx/tools/_helpers.py: 新增兩個安全 helper 函式（+  imports 置頂）。
- src/agentx/tools/__init__.py: 匯出 extract_web_text, validate_external_url。
- tests/test_tools.py: 移除 stubs、用真實 import、修 monkeypatch 為 _helpers 模組。
- Commit d318027（已 push）。

## Deploy 時間軸 / Commits
| Revision | 改動 | 結果 |
|----------|------|------|
| d318027 | tools: 完成 web helpers wiring + Terminal crash 後 integrity 驗證 | ruff 0 error；3 web tests pass（真實實作）；push 成功 |
| 8535173 | docs: 新增 wrap-up 記錄 for terminal-crash-file-integrity session | wrap-up.md + 最終收工記錄推送到 repo |
| 0e2b231 | docs: 更新 wrap-up 記錄（補第二 commit 8535173 資訊 + 最終收工確認） | 最終完整記錄（含最新 sha）推送到 repo |

## 驗證
- `uv run ruff check` on the 3 files: passed.
- `uv run pytest ...` (the 3 web tests): passed.
- Python import + runtime behavior check: passed.
- Git fsck / no locks / no partial files / no swp: clean.
- Crash report: exact match, no other impact.

## Open issues / Follow-up
1. 實作真正的 web_fetch Tool（builtin.py），讓 /fetch 命令與 cli handle 能運作（目前會 unknown tool）。
2. 修復 test_tools.py 其他因 ToolRegistry 建構式改變導致的舊測試失敗。
3. 建議長 session 使用 tmux 保護 TUI view 避免 Terminal crash。

## 參考
- memhall: project:agentx episode 01KT406YXNWHPD6ZE8J2B4BM8S (wrap-up terminal-crash-file-integrity)
- session dir: ~/Documents/agent-council/2026-06-02-terminal-crash-file-integrity/wrap-up.md
- Commits: d318027 (main changes) + 8535173 (wrap-up doc) + 0e2b231 (final update + 完整記錄)
- 相關：MT22 merge 狀態、test comment "temporarily unavailable after merge"

## 最終收工確認
- 所有記錄已完整：memhall + session dir + repos doc + daily log + git。
- Git 最終狀態 clean。
- 無 crash 相關 loose ends。
- Temp 清理完成。
