# agentX 本機部署指南

本機服務：llama.cpp (Gemma 4 26B) + Memory Hall + Ollama (embedding)。

## 快速啟動（複製貼上即可）

```bash
AGENTX_BACKEND=llamacpp \
AGENTX_MEMORY_HALL_URL=http://127.0.0.1:9100 \
agentx
```

## 完整指令（含所有參數）

```bash
AGENTX_BACKEND=llamacpp \
AGENTX_LLAMACPP_URL=http://127.0.0.1:8080 \
AGENTX_MODEL=gemma-4-26B-A4B-it-Q4_K_M \
AGENTX_MEMORY_HALL_URL=http://127.0.0.1:9100 \
agentx
```

## 寫入 .env（之後直接 `agentx` 就好）

在 agentX 專案的 `.env` 或 shell profile 加入：

```bash
export AGENTX_BACKEND=llamacpp
export AGENTX_LLAMACPP_URL=http://127.0.0.1:8080
export AGENTX_MODEL=gemma-4-26B-A4B-it-Q4_K_M
export AGENTX_MEMORY_HALL_URL=http://127.0.0.1:9100
```

## 切回 Ollama

```bash
AGENTX_BACKEND=ollama AGENTX_MEMORY_HALL_URL=http://127.0.0.1:9100 agentx
```

或不設 `AGENTX_BACKEND`（預設就是 ollama）。

## 確認連線狀態

進入 agentX 後執行：

```
/doctor
```

預期結果：
- `llm (llamacpp) ✓ http://127.0.0.1:8080 models=1`
- `memory_search ✓`

## 本機服務資訊

| 服務 | Port | 用途 | 管理方式 |
|------|------|------|----------|
| llama.cpp | 8080 | Gemma 4 26B 推理 | 手動 |
| llama.cpp | 8090 | Embedding (Ollama blob) | 手動 |
| Ollama | 11434 | Ollama daemon | systemd |
| Memory Hall | 9100 | Agent 記憶服務 (qwen3-embedding:0.6b) | systemd user service |

### Memory Hall 管理

```bash
systemctl --user status memory-hall     # 看狀態
systemctl --user restart memory-hall    # 重啟
journalctl --user -u memory-hall -f     # 看 log
curl http://127.0.0.1:9100/v1/health   # 健康檢查
```
