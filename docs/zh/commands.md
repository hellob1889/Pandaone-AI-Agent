# 命令参考

完整 CLI 命令清单。所有命令支持 `--root <path>` 指定项目根（默认当前目录）。

## init — 初始化项目

```bash
pandaone init [--root PATH]
```

**作用**：在项目根创建 `.pandaone/` 目录，包含：
- `config.json` — 17 文本 + 24 二进制扩展名配置
- `pandaone.jsonl` — 审计日志（JSON Lines）
- `binary_snapshots.json` — 二进制文件 SHA256 字典

**选项**：
- `--ext .py .md .json ...` — 自定义保护扩展名（覆盖默认）
- `--binary-ext .png .pdf ...` — 自定义二进制扩展名

## lock / unlock — 锁定/解锁文件

```bash
pandaone lock [--root PATH]
pandaone unlock [--root PATH]
```

**作用**：根据 `protected_extensions` 列表 chmod 所有受保护文件。

**Windows**：`attrib +R` / `-R`
**macOS/Linux**：`chmod 444` / `chmod 644`

## write — 审计写入（核心命令）

```bash
pandaone write \
    --file <RELATIVE_PATH> \
    --reason "改动原因" \
    --problem "解决的问题" \
    --approach "采用的方法" \
    [--old "原文"] [--new "新文"] \
    [--content "完整新内容"] \
    [--from-file <PATH>] \
    [--content-base64 "BASE64"]
```

**文本文件**：用 `--old/--new` 或 `--content` 指定新内容
**二进制文件**：用 `--from-file` 或 `--content-base64`

**注意**：`--reason` / `--problem` / `--approach` 是**强制的**——缺一不可。

**返回**：
```
[APPROVED] {"status":"APPROVED","commit":"<hash>","audit_id":"audit_xxx","file":"..."}
```

## log — 查询审计历史

```bash
# 命令行查看
pandaone log [--root PATH] [--last N] [--status STATUS]

# 导出（13 种格式）
pandaone log [--root PATH] --format <fmt> --output <file>
```

**支持的格式**：
- `text` / `txt` — 纯文本
- `csv` / `tsv` — 表格
- `json` — 结构化
- `yaml` / `yml` — YAML
- `md` / `markdown` — Markdown
- `html` — 网页
- `xlsx` / `excel` — Excel
- `docx` / `word` — Word
- `pdf` — PDF（含中文支持）
- `sqlite` / `db` — SQLite
- `rst` — reStructuredText
- `asciidoc` / `adoc` — AsciiDoc

## status — 项目状态仪表盘

```bash
pandaone status [--root PATH]
```

显示：
- [L1] 文件锁状态（锁定数 / 总数）
- [L2] watchdog 进程状态
- [L5] CLI 自指纹校验
- [审计统计] APPROVED / REJECTED / UNAUTHORIZED 计数
- [最近 N 条] 最新审计记录
- [Phase 5] 二进制 snapshot 状态

**三态语义**（v0.7.35，与 `pandaone doctor` **共用同一份判据**）：
- `[N/A]` 该层从未启用（不是失败）
- `[OK]` 配置过且通过
- `[WARN]` 通过但基线不可比（例如 pip 版与 exe 版形态切换）
- `[FAIL]` 配置过但坏了（例如锁被解除、watchdog PID 被复用、指纹被篡改）

退出码：`0` = 正常；`1` = 项目未初始化；`3` = 有层处于 `[FAIL]`（与 `doctor` 一致）。

## install-hook — 安装 L3 pre-commit hook

```bash
pandaone install-hook [--root PATH]
```

**前提**：项目是 git 仓库（`.git/` 存在）。

**安装**：
- `.git/hooks/pre-commit` — shell 启动器
- `.pandaone/pre-commit-check.py` — Python 校验逻辑

## watch — 启动 L2 watchdog

```bash
# 前台运行（调试用）
pandaone watch [--root PATH]

# 后台运行
pandaone watch [--root PATH] --daemon
```

后台运行后：
- PID 写入 `.pandaone/.watchdog_pid`
- 日志写入 `.pandaone/watchdog.log`

## install-git — 自动安装 git

```bash
pandaone install-git
```

Windows 上下载 Portable Git。

## ci — L7 CI 验证

```bash
pandaone ci [--root PATH] [--base REF]
```

**base** 选项：基线引用（默认 `HEAD~1`）

**返回**：
- 退出码 0：所有变更都有审计
- 退出码 1：存在未审计变更（打印 violation 详情）

## update-fingerprint — 更新 CLI 自指纹

```bash
pandaone --update-fingerprint <CODE>
```

合法更新 CLI 后调用，需要用户传入 4 位确认码（防误操作）。

默认密码为 `0000`（本地单用户场景）。生产 / CI / 多用户环境可通过环境变量
`PANDAX_FP_PASSWORD` 覆盖默认密码，源码不再含"权威"明文。

---

## MCP 命令

`pandaone-mcp` — 启动 MCP server（stdio JSON-RPC）。

不直接调用，由 MCP client（Claude / Cursor / Trae）连接。

暴露 12 个工具：`pandaone_init` / `pandaone_lock` / `pandaone_unlock` / `pandaone_write` / `pandaone_log` / `pandaone_status` / `pandaone_doctor` / `pandaone_install_hook` / `pandaone_watch` / `pandaone_install_git` / `pandaone_fingerprint_update` / `pandaone_ci`

详见 [MCP 集成](mcp-integration.md)。

---

## 退出码约定

| 退出码 | 含义 |
|---|---|
| 0 | 成功 |
| 1 | 拒绝（CI 验证失败 / bypass 拦截 / 验证不通过） |
| 2 | git 工作目录不干净 |
| 3 | 测试失败 |
| 4 | build 失败 |
| 5 | 元数据不合法 |
| 6 | 上传失败 |

---

[← 返回首页](index.md) | [查看 7 层防御详解](defense-layers.md) | [查看 MCP 集成](mcp-integration.md)