# AI Agent 写代码谁来审计？我做了一个 MCP 工具给每行变更打 AI 凭证

> 标签：`AI编程` `Claude` `Cursor` `Trae` `MCP` `代码审计` `开源`

用 AI 写代码一年多，最大的痛苦不是 AI 写得不好，而是 **AI 写完之后我完全不知道它为啥这么写**。

`git commit -m "fix bug"` 里看不出问题是什么、解决方案是什么、为什么选 A 方案而不是 B 方案。

于是我做了一个叫 [Pandaone Guard](https://github.com/hellob1889/Pandaone-AI-Agent) 的 MCP 工具，强制 AI 改代码前必须留三段式审计记录。

---

## 一、为什么需要 AI 代码审计

我现在用 Claude / Cursor / Trae 写代码的工作流：

```
我："给支付模块加退款功能"
AI：3 分钟改了 200 行，8 个文件，新增 2 个依赖
    "Done!"
```

我 `git diff` 看了下，**改了什么一目了然，但为什么这么改完全没记录**：

- 退款逻辑为啥用 Decimal 而不是 float？
- 为啥引入 stripe-sdk 这个新依赖？
- 为啥删掉我之前的 unit test？

3 个月后线上出 bug，on-call 工程师翻 git log 只看到 "fix bug"，翻 Slack 也没人记得为啥这么写。

**这就是 AI 时代的"无主代码"**。

---

## 二、Pandaone Guard 是什么

[GitHub: hellob1889/Pandaone-AI-Agent](https://github.com/hellob1889/Pandaone-AI-Agent)

- 免费、MIT 开源
- 一个 **MCP server**（Model Context Protocol）
- 提供 **11 个工具**，AI 可以调用
- 核心功能：AI 改文件前必须 `pandaone_write` 写一段结构化说明（problem / reason / approach 三段式）
- 写完自动追加到 `.pandaone/pandaone.jsonl` 审计日志
- git pre-commit 钩子强制拦截未审计的变更

效果：**每一行 AI 代码都有出处可查**。

---

## 三、实拍截图（不是 mockup）

### 1. `pandaone write` 命令

![pandaone write](https://raw.githubusercontent.com/hellob1889/Pandaone-AI-Agent/main/assets/terminal-write.png)

### 2. `pandaone status` 项目仪表盘

![pandaone status](https://raw.githubusercontent.com/hellob1889/Pandaone-AI-Agent/main/assets/terminal-status.png)

### 3. Web 实时仪表盘（15 条审计 · claude/cursor/trae 三方）

![dashboard](https://raw.githubusercontent.com/hellob1889/Pandaone-AI-Agent/main/assets/dashboard.png)

---

## 四、6 层防御体系

我把保护分成独立可关的 6 层，按需启用：

| 层级 | 机制 | 防的是什么 |
|---|---|---|
| L1 文件保护格式 | `.jsonl` 审计文件不可被 AI 改 | 防审计日志被污染 |
| L2 文件锁 | `pandaone_lock` / `unlock` | 防敏感文件被 AI 乱改 |
| L3 审计日志 | `pandaone write` | 强制结构化说明 |
| L4 pre-commit 钩子 | 未审计的 commit 直接拒 | 防"先 commit 再补审计" |
| L5 CI 验证 | `pandaone ci` | 防本地绕过钩子 |
| L6 调度对账 | 定时 cron | 防审计与现实脱节 |

每层都能独立测试。整个工具 3000 行 Python，依赖只有 `click` + `rich`，纯本地运行，零外部调用。

---

## 五、一条审计记录长什么样

```bash
pandaone write src/payment/refund.py \
  --problem "退款计算用整数除法导致 JPY 精度丢失" \
  --reason "客户工单 #4521 — 12 起投诉反映 1 日元差额" \
  --approach "改用 Decimal + ROUND_HALF_UP，通过 __round__ 保持公开 API 稳定"
```

产生的 JSONL 记录：

```json
{
  "timestamp": "2026-09-15T08:14:23Z",
  "ai_agent": "claude-3.5-sonnet",
  "file": "src/payment/refund.py",
  "problem": "退款计算用整数除法导致 JPY 精度丢失",
  "reason": "客户工单 #4521 — 12 起投诉反映 1 日元差额",
  "approach": "改用 Decimal + ROUND_HALF_UP，通过 __round__ 保持公开 API 稳定",
  "tags": ["bugfix", "financial-correctness"]
}
```

对比 `git commit -m "fix refund bug"`，on-call 工程师 3 个月后能直接看到原始意图。

---

## 六、5 分钟上手

```bash
pip install pandaone-guard==0.7.14
pandaone init
pandaone write README.md \
  --reason "首次审计" \
  --problem "配置工具" \
  --approach "演示审计流程"
pandaone status
```

接 Claude / Cursor / Trae（复制到 MCP 配置）：

```json
{
  "mcpServers": {
    "pandaone-guard": {
      "command": "pandaone-mcp",
      "args": [],
      "env": {
        "PANDAX_FP_PASSWORD": "0000",
        "PANDAX_LANG": "zh"
      }
    }
  }
}
```

ChatGPT 直连（Developer Mode）也支持，README 里给了完整 5 步指引。

---

## 七、和现有工具的区别（诚实版）

| 维度 | linter / ruff | git log | **Pandaone** |
|---|---|---|---|
| 语法对错 | ✓ | ✗ | ✗ |
| 改了什么 | ✗ | ✓ | ✓ |
| 为啥改 | ✗ | 模糊 | **结构化** |
| AI 凭证 | ✗ | ✗ | **✓** |
| 拦截未审计 | ✗ | ✗ | **✓（pre-commit）** |

**Pandaone 不是 linter**（不管代码好不好），**不是 git 替代**（不记录"改了啥"，那个 git 干），**专做 AI 改动的可追溯性**。

---

## 八、安全边界（不藏着的边界）

诚实声明 Pandaone **不是**银弹：

1. **AI 可以撒谎** — 它可以在审计记录里写"我改了 README"但实际改了 `auth.py`。但这个谎言现在是**永久**写在 JSONL 里的。这是关键洞察：**"你必须用书面撒谎"**比"你必须撒谎"门槛高得多。
2. **不替代 code review** — 干净的审计记录 ≠ 正确的代码。人还是要读意图。
3. **不是独立的安全屏障** — 配合 git hooks + CI + 人工 review 三道关才完整。

---

## 九、M8ven Trust Index A 级认证

最近把 11 个工具的 MCP annotations 全补齐了（`readOnlyHint` / `destructiveHint` / `idempotentHint` / `openWorldHint`），M8ven 评分从 74 涨到 **100/A**：

- Verified Publisher 徽章
- Live Monitored（每次 push 自动重测）
- 任何新依赖 CVE 立即告警

---

## 十、Roadmap

- **v0.7.15**（本周）：审计依赖关系图可视化
- **v0.8.0**（下月）：可选 OPA 策略引擎（"禁止 AI 改 `/auth/*`"）

---

## 链接

- GitHub: https://github.com/hellob1889/Pandaone-AI-Agent
- PyPI: https://pypi.org/project/pandaone-guard/
- M8ven: https://m8ven.ai/mcp/hellob1889-pandaone-ai-agent
- V2EX 推广稿: https://github.com/hellob1889/Pandaone-AI-Agent/blob/main/docs/V2EX_POST_pandaone.md

**MIT 协议，永远免费，本地优先，零遥测。**

如果你的团队在用 AI 写生产代码，给自己一道 AI 凭证吧。

欢迎试用、提 issue、PR、Fork。