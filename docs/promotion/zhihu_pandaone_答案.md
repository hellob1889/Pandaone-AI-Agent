# Claude / Cursor 改完代码，如何追溯 AI 改了什么、为什么改？

> 问题背景：越来越多团队用 Claude Code / Cursor / Trae 辅助编码，但代码审计完全跟不上 AI 改动的速度

---

## 现状：AI 写代码是黑盒

假设场景：

```
你："给 user service 加 OAuth2"
AI：（改了 4 个文件，+200/-80 行，加了一个新依赖）
    "搞定！"
```

你 git diff 一看，改了什么**一目了然**。但这几个问题 AI 不会主动告诉你：

1. **为啥用 stateful session 而不是 stateless JWT？**
2. **为啥引入 `python-jose` 而不是已有的 `authlib`？**
3. **为啥删了我之前的 unit test？**
4. **3 个月后线上出 bug，怎么复盘 AI 当初的决策？**

`git log` 只有一行 `feat: add OAuth2`，`git blame` 只到 commit hash，没有 AI 的原始意图。

---

## 解决方案：强制 AI 写"变更凭证"

我开源了一个工具叫 **[Pandaone Guard](https://github.com/hellob1889/Pandaone-AI-Agent)**（MIT 免费），核心思路：

**AI 改文件前必须先调用 `pandaone_write` 写一段三段式说明**：

```
pandaone write src/auth/oauth.py \
  --problem "OAuth 流程缺少 CSRF token 校验" \
  --reason "安全工单 #231 — 外部渗透测试发现的潜在 CSRF 漏洞" \
  --approach "在 /oauth/start 生成 state 参数，/oauth/callback 验证。保留原有 session cookie 流程。"
```

写完自动追加到 `.pandaone/pandaone.jsonl` 审计日志，**git pre-commit 钩子强制检查**——未审计的 commit 直接拒绝。

效果：

```json
{
  "timestamp": "2026-09-15T08:14:23Z",
  "ai_agent": "claude-3.5-sonnet",
  "file": "src/auth/oauth.py",
  "problem": "OAuth 流程缺少 CSRF token 校验",
  "reason": "安全工单 #231",
  "approach": "在 /oauth/start 生成 state 参数..."
}
```

3 个月后 on-call 工程师直接看到 AI 当初为啥这么改，不用翻 Slack / Notion / 工单系统。

---

## Pandaone Guard 的 6 层防御

我故意拆成独立可关的 6 层（每层都能 opt-out）：

- **L1 文件保护格式**：`.jsonl` 审计文件 AI 改不动
- **L2 文件锁**：`pandaone_lock / unlock` 手动保护敏感文件
- **L3 审计日志**：`pandaone_write` 强制结构化说明
- **L4 pre-commit 钩子**：未审计 commit 拒
- **L5 CI 验证**：`pandaone ci` 防本地绕过
- **L6 调度对账**：定时 cron 防审计与现实脱节

---

## 5 分钟接入

```bash
pip install pandaone-guard==0.7.14
pandaone init
pandaone install-hook
```

接 Claude Code / Cursor / Trae：

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

ChatGPT 直连（Developer Mode）也支持，README 有 5 步指引。

---

## 几个常见疑问

### Q1：AI 可以绕过吗？直接在审计里写"我啥也没改"？

可以。但这个谎言现在是**永久**写在 JSONL 里的。这正是核心洞察：**"你必须用书面撒谎"**比"你必须撒谎"门槛高得多。3 个月后出 bug，对比代码 diff 和审计记录，一眼看出 AI 在撒谎。

### Q2：和 git hook + 人工 review 比有啥区别？

- git hook：拦截，但没说为啥改
- 人工 review：知道为啥改，但慢
- Pandaone：**结构化强制 AI 说出为啥改**，review 时直接对照

### Q3：会拖慢 AI 写代码吗？

实测几乎无感。AI 调 `pandaone_write` 是单次 API 调用，100ms 量级。AI 写代码本身是秒级。

### Q4：和现有 lint / SAST 工具冲突吗？

不冲突。Pandaone 管"AI 凭证"（为啥改、怎么改），lint 管"语法对错"，SAST 管"漏洞"。三个正交。

### Q5：能用于代码合规审计吗（如 SOC2、ISO27001）？

合规审计需要的"变更理由 + 责任人 + 时间戳"三件套，Pandaone 全覆盖。但 Pandas 是**辅助**证据，不是替代品——人审还是要的。

---

## 现在能用的版本

- **v0.7.14** 已发布 PyPI
- 11 个 MCP 工具（annotations 全齐）
- 15 个测试，100% 覆盖 MCP server
- M8ven Trust Index **100/A**（Verified Publisher + Live Monitored）
- 137 KB wheel，pip 一键装

---

## 链接

- GitHub: https://github.com/hellob1889/Pandaone-AI-Agent
- PyPI: https://pypi.org/project/pandaone-guard/
- 文档: https://github.com/hellob1889/Pandaone-AI-Agent/blob/main/docs/zh/index.md
- M8ven: https://m8ven.ai/mcp/hellob1889-pandaone-ai-agent

MIT 协议、永久免费、本地优先、零遥测。

如果你也在被 AI 黑盒改动困扰，欢迎试用 / 提 issue / 贡献代码。