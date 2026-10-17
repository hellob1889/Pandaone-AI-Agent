# v0.7.21.3 Release Notes

## 🎯 Cosmetic bug fix — FP_PATH 写裸 hex 应走 json 格式

### 背景

v0.7.21.2 重写 `check_fingerprint` 改用 json 格式存指纹：
```json
{
  "version": "0.7.21.x",
  "hash": "<sha256 hex>",
  "stored_at": "2026-10-17T10:04:37Z"
}
```

但 `src/pandaone/cli_chunks/part_006.py` 漏改 2 处：
- **trust_default 路径** (line 354)：装机 user 跑 `pandaone install-context --trust-default` 自动 update fingerprint 走这分支
- **`--update-fingerprint` handler** (line 395)：装机 user 显式跑 `pandaone --update-fingerprint 0000` 走这分支

两处都仍写 `FP_PATH.write_text(new_fp, encoding="utf-8")` 裸 hex 64 字符。

### 影响

- **影响等级**: cosmetic（功能 OK，跑 `install-context` 走 `check_fingerprint` 自动触发 migrate 救回）
- **症状**: 装机 user 主动跑 `pandaone --update-fingerprint 0000` 后，`~/.pandaone_fp.txt` 是裸 hex 64 字符，跟 README 描述的 json 格式不一致
- **真破坏**: README vs code 漂移 + 装机 user 升级 v0.7.21.3 之前 FP_PATH 内容跟代码预期不一致

### 修复 (v0.7.21.3)

`src/pandaone/cli_chunks/part_006.py` 2 处都改 `_save_fp(_get_pandaone_version(), new_fp)`:

```python
# 旧 (cosmetic bug):
FP_PATH.write_text(new_fp, encoding="utf-8")

# 新 (v0.7.21.3):
_save_fp(_get_pandaone_version(), new_fp)
```

`_save_fp` 是 v0.7.21.2 加的 helper，存 json 格式 `{version, hash, stored_at}`。

### Test 覆盖

新增 `tests/test_update_fp_writes_json_v0721_3.py` 3 个 test:
1. `test_v0721_3_update_fingerprint_writes_json_format` — 验 `--update-fingerprint` handler 触发后 FP_PATH 是合法 json 含 `version/hash/stored_at`
2. `test_v0721_3_trust_default_writes_json_format` — 验 `--trust-default` 自动 update-fp 后 FP_PATH 是合法 json
3. `test_v0721_3_no_bare_hex_in_part_006` — static check 防回归: part_006.py 不应再有 `write_text(new_fp` 模式

### 装机升级

```powershell
irm https://raw.githubusercontent.com/hellob1889/Pandaone-AI-Agent/main/scripts/install-update-latest.ps1 | iex
```

升级到 v0.7.21.3 后:
- 现存 FP_PATH 裸 hex 格式 → 第一次跑 `pandaone install-context` 或 `pandaone --update-fingerprint 0000` 自动迁移到 json
- 不需要额外操作

### 升级链路

| Version | 重点 |
|---|---|
| v0.7.20 | P0-1 install-context 修复 / P0-2 multi-file hash / P0-3 去 --trust-default |
| v0.7.21 | install-context Win11 锁 try/except per BASE_KEY skip |
| v0.7.21.2 | 指纹存版本号 + default auto-refresh (痛点 trigger 修复) |
| **v0.7.21.3** | **2 处 FP_PATH.write_text → _save_fp (cosmetic bug fix)** |

老八 0 副作用守则: v0.7.21.3 仅动 part_006.py 2 处 + 新 test + pyproject version, 不动 v0.7.21.2 tag/release。
