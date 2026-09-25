# TODO

## Open

- [ ] **Separate llama-swap model instances for Work-Loop vs. interactive chat.**
  Work-Loop and interactive OpenCode sessions both use `llama-swap/mlx/Qwen3.8-27B-6bit` (changed 2026-09-24; the default in `~/.config/opencode/opencode.json` is also that model). Sharing one instance means the loop's prompt-cache churn can evict the chat session's KV cache.
  - Define two explicitly named instances in the llama-swap config on mac-studio (e.g. `mlx/Qwen3.8-27B-6bit-workloop` and `mlx/Qwen3.8-27B-6bit-chat`), and check both fit in unified memory at the same time.
  - Point `harness.model` in `config.json` at the Work-Loop instance, and the default in `opencode.json` at the chat instance.
  - Update or remove the stale `model_note` in `config.json` (it still describes the old llama.cpp vs. MLX split).
