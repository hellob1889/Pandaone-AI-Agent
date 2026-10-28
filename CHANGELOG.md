# Changelog

All notable changes to Pandaone AI Agent will be documented in this file.

## [0.7.34.1] - 2026-10-29

**把 `doctor` 从「存在性体检」改造成「可执行性体检」，并修掉 Windows 上两个真实用户会踩的坑。**

本版起因是 v0.7.33.0 的真机回归教训：`install-hook` 在 exe 形态下完全失效，而 `doctor` 的 L3 层只检查
"hook 文件在不在"、不检查"安装命令能不能跑"，所以整个缺陷长期潜伏、doctor 一直报 `[OK]`。
**"状态全绿"不等于"功能可用"** —— 这一版把这件事从根上解决。

### 本次发布包含什么

| 来源版本 | 主题 |
|---|---|
| 0.7.34.1 | **doctor 8 层全部改成真检查**：从"存在性代理"变成"该防护实际能不能工作"，并首次让层级失败真正反映到退出码 |
| 0.7.34.1 | **修静默安装不更新 IDE 的 MCP 配置**：用户升级后 IDE 里仍跑旧版 MCP，v0.7.31.0 修的编码 bug 完全不生效 |
| 0.7.34.1 | **修 Windows 上 `SO_REUSEADDR` 允许抢占他人监听端口**：同机并发跑两个 `pandaone serve` 会共享端口、请求被随机分发 |
| 0.7.34.1 | `_load_install_hook_module` 源码形态路径修正（原实现恒返回 None） |

### Fixed: `doctor` 的 8 层里有 5 层是「存在性判定」

**症状**：某层防护实际已经失效，`doctor` 却报 `[OK]`。

**根因**：`cmd_doctor.py` 里 L1/L2/L3 是**内联字面量**，连独立的 check 函数都没有：

- **L1_file_lock**：`{"ok": True, "note": "python-only (attrib/chmod)"}` —— **无条件 True**，从不实际检查。
  项目从没执行过 `pandaone lock`，doctor 照样报 L1 就绪。
- **L2_watchdog_rollback** / **L3_pre_commit_hook**：`ok = git 是否安装` —— git 装了就算 OK。
  看门狗进程没起、hook 根本没装、`protected_extensions` 为空、hook 被改成 `exit 0` 空壳，全部报 OK。
- **L4_startup_check**：查的是 `import watchdog`（那是 L2 的依赖），而 L4 的真实机制是"启动时加载项目 README 摘要"。
- **L6_tamper_detection**：只数 `APPROVED` / `REJECTED`，**漏掉 `UNAUTHORIZED`** —— 而 `UNAUTHORIZED` 才是
  看门狗抓到的真篡改状态。一份满是 UNAUTHORIZED 的日志，doctor 会显示"0 APPROVED + 0 REJECTED"，看起来比干净还干净。
- **L7_ci_audit**：用 `__file__` 上溯三级定位 CI 配置，pip 安装形态下解析到 `site-packages/Lib` → **恒 FAIL**。

**更严重的是汇总层**：`overall_ok` 与退出码原本只看 git 与 Python，**层失败完全不影响结果** ——
即使各层判成 FAIL，doctor 照样打印"全部正常"、exit 0。所以不先修汇总层，其他改动全被吃掉。

**修法**：

1. **汇总层先修**：新增 `--root`（默认 cwd），`overall_ok` 纳入层结果，新增退出码 **3**（1=缺 git / 2=Python 过旧 语义不变），
   报告不再打"全部正常"横幅。
2. **每层改成真检查**：
   - L1 枚举受保护文件、统计可写数（复用 `cmd_status` 已有的锁定计数算法）
   - L2 检查 watchdog 可导入 + git **可执行**（`_can_run_git`）+ 有 baseline commit + **看门狗 PID 存活** + frozen 下 `pandaone_guard.exe` 在位
   - L3 检查 hook 存在 + **归属是本工具的**（含 `Pandaone` 标识）+ **LF-only 无 BOM** + check 脚本可编译 +
     **`install-hook` 模块在当前形态可加载** + `protected_extensions` 非空
   - L4 改查 README 摘要加载
   - L5 **先比 `form` 再比 hash**（源码/exe 切换只 WARN，不再误报 TAMPERED）
   - L6 逐行 JSON 解析三态计数，`UNAUTHORIZED > 0` 判 FAIL；审计基线被删判 FAIL
   - L7 改为源码树专属判定（非源码树一律 N/A）
3. **层状态三态化**：区分「**未启用**」「正常」「**已启用但坏了**」。只有第三种才判 FAIL、才影响退出码。
   —— 否则刚 `init` 的普通项目会因为"没 lock、没装 hook"而 4 层全红、exit 3，
   而 `pandaone setup` 本身又不执行 lock 与 install-hook，**没有任何官方流程能让 doctor 返回 0**。

**新增回归测试**：`tests/test_cmd_doctor_layers.py`（34 条）+ 扩写 `tests/test_cmd_doctor.py`。
此前 doctor 的测试**只断言 7 个层名存在**，没有任何一条断言"某层能判 FAIL" —— 这正是缺陷能长期存活的原因。

### Fixed: 静默安装不更新 IDE 的 MCP 配置（用户升级后仍跑旧版 MCP）

**症状**：用户从 0.7.21.3 升级到 0.7.33.0，IDE 里的 MCP 仍���旧版本，**v0.7.31.0 修的 GBK/UTF-8 编码 bug
完全不生效**，`tools/call` 整条链路继续返回 `isError=true`。

**根因（比表面原因深一层）**：`codeaudit.iss` 的 `[Run]` 段里 install-mcp 条目带 `skipifsilent`，
**且** `[Tasks]` 里的 `installmcp` 任务本身带 `Flags: unchecked`（默认不勾选）。
Inno Setup 6 文档明确写着：带 `Tasks:` 的 `[Run]` 条目**只有用户选中该任务才会被处理** ——
所以静默安装下这条根本不执行。

叠加放大：同一次静默安装里 `doctor --clean-conflicts`（**没有** `skipifsilent`，注释明说"静默安装正是需要清理的场景"）
会把 pip 版 `pandaone-mcp.exe` 改名备份，而 IDE 配置里的**裸名** `pandaone-mcp` 此时可能直接指向被改名的文件而启动失败。

**修法**：三处同时改 —— 去掉 `skipifsilent`、去掉 `Flags: unchecked`、加 `UsePreviousTasks=no`（防止升级安装继承上次"已取消勾选"的状态）；
并把 install-mcp 排到 `doctor --clean-conflicts` **之前**，先把 IDE 配置改写成新版本绝对路径再去清理旧版。

**副作用声明**：加 `UsePreviousTasks=no` 会重置任务选择状态，因此**用户此前显式取消过 installmcp 的选择会被覆盖**，
升级后 IDE 配置会被重新写入。缓解是充分的（只改 `mcpServers.pandaone`、写前备份），
但知情权归用户 —— 需要保持原状请在升级后重新勾掉，或改用非静默安装。

> 顺带修正：复核确认 `UsePreviousTasks=no` 在 Inno Setup 6 下会让 `checkedonce` 标志失效，
> 这**反而修好了** `addtopath` 任务升级时被跳过、PATH 前置不更新的老问题。

### Fixed: Windows 上 `SO_REUSEADDR` 允许抢占他人已监听的端口

**症状**：同机并发跑两个 `pandaone serve`（例如一边跑全量测试一边开看板），两个进程**共享同一端口**，
请求被随机分发给其中一个，另一个直接被 RST（`WinError 10054`）。`tests/test_pandax_serve.py`
在 Windows 全量并发下偶发 4 例失败，而**单跑 20/20 全绿**、CI 是 Linux 从不复现。

**根因**：`socketserver.TCPServer.allow_reuse_address` 默认为 1 会设 `SO_REUSEADDR`，
而 **Windows 上 `SO_REUSEADDR` 允许第二个 socket 抢占别人已在 LISTEN 的端口**（Linux 上同样 bind 直接 `EADDRINUSE`）。
实测 Windows + Python 3.11：不带 `SO_REUSEADDR` 的 bind 失败 `errno=10048`，带的 bind 反而成功。

叠加两个放大因素：`start_server` 先用 `_find_free_port()` 探测再让 server 重新 bind，
探测（bind 完立刻 close）与真 bind 之间存在 **TOCTOU 窗口**；测试用例把端口写死成 19000/19100/19200-19204，
URL 也不取 `server.server_address[1]`，于是 `start_server` 顺延后测试打的是**别人的服务**。

**修法**：新增 `_PandaoneHTTPServer`，Windows 上 `allow_reuse_address=False`（Linux/macOS 保留 True 以维持 TIME_WAIT 快速重用），
`server_bind` 改为**原子占端口**（真 bind 成功才算占用，失败顺延到下一个，上限 20 个），
消除探测-占用的 TOCTOU 窗口；实际端口一律以 `server.server_address[1]` 为准。
测试侧改为向 OS 借端口（bind port 0）并使用实际绑定端口，另加端口隔离回归用例。

**验证**：3 个 pytest 进程并发 × 3 轮 = 9/9 全绿（修复前同条件下 16 例失败）；全量套件 547 passed。

### Fixed: `_load_install_hook_module` 源码形态路径恒失效

原实现用 `Path(__file__).resolve().parent.parent / "install_hook.py"`，但 `cli.py` 加载完 chunk 后会把 `__file__`
恢复成 `cli.py` 的路径 → 解析到 `<repo>/src/install_hook.py`（不存在）→ **源码形态下该函数恒返回 None**。

对已发布的 v0.7.33.0 **无用户影响**（该函数只被 frozen 分支调用，源码形态走 subprocess 分支），
但它会让**新的 doctor L3 真检在源码形态下永远误红**。改为同时保留 `parent` 与 `parent.parent` 两个候选路径。

### 升级指引

- **从 0.7.21.3 或更早版本升级**：直接 `pip install --upgrade pandaone-guard` 即可。
  已实测 0.7.21.3(exe) → 0.7.34.1(exe) 与 0.7.21.3(pip) → 0.7.34.1(exe) **两条路径都不会触发指纹自锁**
  （版本号变化走 auto-refresh 分支，该分支排在形态判断之前；0.7.21.3 的 JSON 指纹缺 `form` 字段也有兜底）。
- **升级后建议手动跑一次** `pandaone install-mcp --client auto --absolute-command`，
  确保 IDE 里的 MCP 指向新版本绝对路径。
- **若 doctor 报某一层 FAIL**：先看该层 note 说明的原因。v0.7.34.1 起 doctor 区分「未启用（N/A）」与
  「已启用但坏了（FAIL）」，只有后者才影响退出码。

### 关于版本号从 0.7.21.3 跳到 0.7.34.1

0.7.22 ~ 0.7.32 这批版本号**从未对外发布过**（一直在开发分支上流转）。
其中 0.7.24 / 0.7.25 / 0.7.26 / 0.7.31 / 0.7.32 真正落地成版本号，0.7.22 / 0.7.23 只活在源码注释里，
0.7.27 ~ 0.7.30 是提交信息里的分组标签。**因此本版是一次聚合发布**，不是逐版演进。
本版不补发过渡版 —— 补一个 `0.7.21.4` 无法消除跳跃，反而会造出一个既不属于 0.7.21 也不属于 0.7.34 的空壳版本。

## [0.7.33.0] - 2026-10-26

**自 v0.7.21.3 之后的第一个对外发布版本。**

0.7.24.0 ~ 0.7.32.0 这一串版本号始终只在开发分支上流转，**从未发布到 PyPI / GitHub Release**；
它们各自的真机回归结论与修复内容完整保留在下方各段里。本次把这一整批改动一次性发布出去。

### 本次发布包含什么

| 来源版本 | 主题 |
|---|---|
| 0.7.31.0 | MCP 子进程输出编码错配（GBK 解 UTF-8）导致整条 `tools/call` 链路瘫掉；全仓 9 处 `subprocess` 显式指定 encoding |
| 0.7.31.0 | `path_conflicts` 入口名硬编码 Windows 后缀 → Linux/macOS 上 PATH 抢占检测**静默失效** |
| 0.7.31.0 | `git_ops` 本地镜像回退产出嵌套布局，与 `git clone --mirror` 不一致 → 照文档恢复不出来 |
| 0.7.31.0 | `pre-commit` 模板里写死作者本机 `D:\软件\Git\...` 路径 |
| 0.7.32.0 | 上一条的修法（运行时反推安装根）被真机对照实验**证伪** → 改为安装时固化 git 路径 |
| 0.7.33.0 | **真机安装回归新查出的 bug**：`install-hook` 在 exe 形态下完全不可用（详见下节） |

### Fixed: `install-hook` 在 exe 形态下完全不可用（真机回归查出）

**症状**（本机静默安装 0.7.32.0 后实测）：

```
> pandaone.exe install-hook --root D:\repo
pandaone: error: argument command: invalid choice: 'pandaone.install_hook'
```

**根因**：`cli_chunks/part_005.py::cmd_install_hook` 原本用子进程调用 `install_hook.py`：

```python
cmd = [sys.executable, "-m", "pandaone.install_hook", "--root", args.root]
```

源码 / pip 形态下 `sys.executable` 是 python.exe，`-m` 有模块执行语义，没问题；
但 **PyInstaller 冻结后 `sys.executable` 就是 `pandaone.exe` 本身** —— exe 没有 `-m` 语义，
argparse 于是把 `pandaone.install_hook` 当成子命令名，以 "invalid choice" 失败。

**影响面**：CLI 的 `install-hook` 子命令 + MCP 的 `pandaone_install_hook` 工具**两条链路全废**
→ exe 用户在 L3 pre-commit 防御上根本装不上 hook。

**为什么 `doctor` 一直显示 L3 OK**：L3 检查只验证"hook 文件在不在"，**不验证"安装命令能不能跑"**。
所以装不上 hook 的机器，doctor 依然报 `[OK] L3_pre_commit_hook` —— 这正是该 bug 能长期潜伏的直接原因。

**修法**：冻结形态下改为**进程内直接调用** install_hook 模块的函数，不再起子进程。

- 模块加载：不能用 `from pandaone.install_hook import ...` —— 冻结包的模块表（PYZ）里没有它
  （它只作为数据文件被整棵树拷进 `_internal/pandaone/`），静态 import 会 ImportError；
  改为按文件路径 `importlib` 加载 `_internal/pandaone/install_hook.py`，
  这样模块内的 `ROOT = Path(__file__).parent / "templates"` 正好指向**冻结包内**那份模板。
- 非冻结形态保持原有 subprocess 路径不变。

**同类代码复核**：`cmd_setup.py` / `cmd_upgrade.py` / `pandaone_mcp\__main__.py` 早就有 frozen 感知
（用 `sys.executable serve` 或同目录 `pandaone.exe`），**只有 install-hook 这一条漏了**，
已一并核对确认无其他遗漏。

**新增测试**：`tests/test_install_hook_frozen.py`（6 项）——
静态校验 frozen 分支不再出现 `sys.executable -m` + 行为校验进程内调用路径 + 模板常量可解析。

### 为什么版本号是 0.7.33.0

**因为 0.7.32.0 已经在真机上装过了**（`%LOCALAPPDATA%\Pandaone`，`~/.pandaone_fp.txt` 记着 `version=0.7.32.0`）。

L5 自指纹记录的是 `{version, hash, form}` 三元组，而 `check_fingerprint()` 只在两种情况下自动刷新：

- **版本号变了**（升级）；
- **运行形态变了**（源码树 ⇄ PyInstaller 打包版 —— 两者文件集合本来就不同）。

于是「同版本号重打包」会落进第三种情况：**版本号不变 + 形态不变 + hash 变了** = 判定为**真篡改**
→ 整个 CLI 锁死，连 `--version` 都打不开。

仓库自带的 `build_pyinstaller.py::check_version_bump` 已经把这条规则做成了构建门禁：
同版本号重打包会被直接拒绝，除非显式加 `--allow-same-version`（该选项的注释写明「仅本地验证用」）。

所以发布必须抬版本号 —— 本次从 0.7.32.0 抬到 **0.7.33.0**。

## [0.7.32.0] - 2026-10-26

> 未发布的中间版本。0.7.32.0 只在本机做过一次真机安装回归，
> **回归反而查出 `install-hook` 的真 bug**（见上方 0.7.33.0 段落），
> 因此对外发布版本直接定为 **0.7.33.0**，0.7.32.0 从未发布。

## [0.7.31.0] - 2026-10-25

真机回归探针的最后一关卡住：`pandaone_init` 这类 **MCP tools/call 全部返回 isError=true**。
根因是编码，不是业务逻辑。

### Fixed: MCP 用系统 locale(GBK) 解码子进程的 UTF-8 输出 —— 整条 tools/call 链路瘫掉

**症状**（真机实测，`%LOCALAPPDATA%\Pandaone\pandaone-mcp.exe`）：

```
tools/call pandaone_init -> {"isError": true,
    "content": [{"text": "[stderr] expected string or bytes-like object, got 'NoneType'"}]}
MCP 进程 stderr:
    UnicodeDecodeError: 'gbk' codec can't decode byte 0xae in position 17
      File "subprocess.py", line 1599, in _readerthread
```

**根因链**（四步，每一步都合理，合起来必死）：

| 步 | 发生了什么 |
|---|---|
| 1 | CLI 子进程输出的是 **UTF-8** 字节（父进程 env 带 `PYTHONIOENCODING=utf-8` 时必然如此；PyInstaller bootloader 同理） |
| 2 | `subprocess.run(..., text=True)` **不指定 encoding** -> Python 用**系统 locale 编码**解码 = 中文 Windows 的 **GBK** |
| 3 | GBK 解码器读 UTF-8 字节 -> `UnicodeDecodeError` -> subprocess 内部 **reader 线程直接死掉** -> `r.stdout` / `r.stderr` 变成 **None** |
| 4 | `_strip_ansi(None)` -> `re.sub(pattern, None)` -> `TypeError: expected string or bytes-like object, got 'NoneType'` |

**为什么一直没被发现**：源码树跑 `pytest` 时父进程通常不带 `PYTHONIOENCODING`，
子进程按 locale 输出 GBK、GBK 解 GBK —— 恰好对上了。只有**真机 exe + 特定 env 组合**才炸。

**修复**（两端对齐，从此不依赖机器 locale）：

- `src/pandaone_mcp/__main__.py::_run_cli`
  - 给子进程显式注入 `PYTHONIOENCODING=utf-8` -> 输出恒为 UTF-8 字节；
  - 父进程显式 `encoding="utf-8", errors="replace"` -> **任何解码异常都被吞掉**，reader 线程不会再死；
- `src/pandaone_mcp/__main__.py::_strip_ansi` -> 对 `None` / 非字符串输入做防御，返回 `""` 而不是抛 TypeError；
- `src/pandaone_mcp/__main__.py::serve_stdio`
  - `sys.stdout.reconfigure(encoding="utf-8")` —— **MCP over stdio 协议要求 UTF-8**；
    不切的话 Windows 上 stdout 用 GBK 编码，中文响应会被客户端按 UTF-8 解成乱码；
  - `sys.stdin.reconfigure(encoding="utf-8", errors="replace")` —— 客户端发来的 UTF-8 中文请求同理。

### Fixed: 全仓 9 处 `subprocess` 捕获输出没显式指定 encoding（同一根因的潜伏点）

MCP 只是第一个爆的。同一类地雷全仓还有 9 处，全部修掉：

| 文件 | 场景 | 风险 |
|---|---|---|
| `cli_chunks/part_003.py` (3 处) | `git add` / `git commit` / `git log` | **本轮提交就会踩** —— `git commit -m <中文>` 的回显含中文，UTF-8 字节被 GBK 解 -> `r.stderr.strip()` 触发 AttributeError on None |
| `cli_chunks/part_005.py` (2 处) | `install_hook` 子模块、`_git_run` | 同上 |
| `git_installer.py` (3 处) | `git --version`、git 安装过程日志 | git 安装日志含中文 |
| `pandaone_guard/__main__.py` (1 处) | `git checkout HEAD -- <file>` | 守护进程回滚路径 |
| `templates/pre-commit-check.py` (1 处) | `git diff --cached` | **L3 审计门禁本身** —— 门禁挂掉 = 审计形同虚设 |

统一改成 `text=True, encoding="utf-8", errors="replace"`。
`errors="replace"` 是刻意的：解码失败宁可显示乱码，也不能让 reader 线程死掉把返回值变成 None。

### Tests

- 新增 `tests/test_mcp_encoding.py`（11 例）：
  - `_strip_ansi` 的 None / 空串 / ANSI 剥离 / 中文保留；
  - `_run_cli` 强制 `encoding="utf-8"` + `errors="replace"` + 子进程 env 注入 `PYTHONIOENCODING=utf-8`；
  - `_run_cli` 在 stdout/stderr 为 None 时优雅降级（不抛 TypeError）；
  - `_run_cli` 超时路径；
  - `_cli_command()` 的 frozen / 源码两种形态；
  - `serve_stdio` 必须把 stdin/stdout reconfigure 到 UTF-8；
  - **AST 扫描守卫**：全仓所有 `capture_output=True` 的 subprocess 调用必须显式带 `encoding`
    —— 防止以后再加一个裸 `text=True` 重演这次事故。
- 基线：`535 passed, 9 skipped` -> `546 passed, 9 skipped`

### Verified

真机探针（`%LOCALAPPDATA%\Pandaone` 下的真 exe）：
- `initialize` -> `serverInfo.version = 0.7.31.0`；
- `tools/list` -> 11 个工具；
- `tools/call pandaone_init` -> **isError=false**，`.pandaone/` 正常建成；
- `tools/call pandaone_status` / `pandaone_log` -> **isError=false**。

### Fixed: 跨平台盲区 —— Ubuntu CI 上 7 个用例变红挖出的三类平台假设

CI 是有价值的：v0.7.31.0 的首轮 Ubuntu CI 连续红两次，第二次暴露出**同一类根因的三个平台假设**。
它们的共同特征是「**不报错、不崩，只是静默失真**」—— 在 Windows 上永远看不见。

| # | 位置 | 现象 | 根因 | 修法 |
|---|---|---|---|---|
| 1 | `src/pandaone/path_conflicts.py` | Linux/macOS 上 `find_all()` / `shadows()` 恒返回空，整套 PATH 抢占检测**静默失效** | 入口名常量只列了 Windows 后缀（`pandaone.exe/.cmd/.bat`），而 POSIX 上 pip 生成的是**无扩展名**的 `pandaone` | 按 `os.name` 分平台构造 `CONSOLE_SCRIPT_NAMES` / `MCP_SCRIPT_NAMES`；同一目录只取第一个命中的名字（避免 `.exe` 与 `.cmd` 被数成两处）；self 命中时继续检查同目录的其它入口（如 `pandaone-mcp`） |
| 2 | `src/pandaone/git_ops.py` | Windows 上产出的本地镜像**照着文档恢复不出来**（`git clone --local` / `clone --bare` / `clone <mirror>/.git` 四种方式实测全部 rc=128） | 回退逻辑产出 `target/.git/` 嵌套布局，与 `git clone --mirror` 的 bare 布局不一致；而 Windows 上 `git clone` 本地路径必然要调 `git-upload-pack`（Git for Windows 的 `cmd/` 只有 `.exe` 没有无后缀 sh 脚本） | 回退改为 `git init --bare` 生成骨架后复制 `objects/refs/packed-refs/HEAD`，并写入 `remote.origin.url` / `fetch` refspec / `mirror` 标记；**两平台布局统一**，且可被 `git --git-dir=<mirror>` 离线读取 |
| 3 | `src/pandaone/templates/pre-commit-check.py` | 模板里写死了作者本机的 `D:\软件\Git\...` 路径 | 早期为绕过 hook 子 shell PATH 为空留下的硬编码，但该模板会**分发到所有用户机器** | 改为优先 `GIT_EXECUTABLE` 与 PATH，再从 git 注入的 `GIT_EXEC_PATH` 反推安装根目录（任意盘符都能命中），最后才退到 `Program Files` 常见位置（**此方案已被下一节的真机对照实验证伪**） |

配套测试改造（`tests/`）：
- `test_cmd_setup_upgrade.py`：入口名按平台取 `CONSOLE_ENTRY` / `MCP_ENTRY`，PATH 拼接改 `os.pathsep`；
- `test_cmd_backup.py` / `test_git_ops.py`：镜像断言兼容两种合法布局，并新增**离线可读 + 内容完整 + 可原样复制**三条真正契约
  （刻意**不用** `git clone` 验证 —— 那测的是 git 的环境，不是我们的备份）。

### Fixed: pre-commit hook 在 Windows 上找不到 git —— 门禁静默失效

上一条修法（删掉模板里写死的 `D:/软件/Git/...`，改成"运行时反推安装根"）在 Windows 上**不成立**，
本节的真机对照实验把它证伪了。

**症状**：Windows 上 `git commit` 被 hook 拦下，stderr 是
`[Pandaone] git call failed: [WinError 2] 系统找不到指定的文件`。
对照实验（同一台机器、同一套测试）：基线（保留硬编码路径）31 passed，改动后 3 个用例变红。

**根因**：Git for Windows 的 hook 环境是"敌意环境"——

| 探针 | hook 里的实际值 | 后果 |
|---|---|---|
| `PATH` | 被重写成 MSYS 风格 | `shutil.which("git")` 按 Windows 语义拼 PATH，必然找不到 |
| PATH 里含非 ASCII 的项 | `D:/软件/Git/cmd` → mojibake `D:/鏉瀄ue.../Git/cmd` | 该路径在磁盘上根本不存在 |
| `GIT_EXEC_PATH` | 同样是 mojibake | 从它反推安装根的候选全部 `isfile=False` |
| `tr` / `grep` | command not found | hook 里连 coreutils 都未必有 |

结论：**hook 运行环境里没有任何一个来源能拿到未损坏的 git 路径**——
含非 ASCII 的 PATH 项被转码坏了，`GIT_EXEC_PATH` 也坏了。
唯一能拿到真值的时刻是**安装时刻**（一个 PATH 完好的普通进程）。

**修法**：把"找 git"从运行时挪到安装时。

| 位置 | 改动 |
|---|---|
| `src/pandaone/install_hook.py` | 安装时用 `_find_git_executable()` 解析 git 绝对路径，写入 `.pandaone/git_exe.txt` |
| `src/pandaone/templates/pre-commit-check.py` | `_resolve_git_exe()` 改为**逐级降级**：环境变量覆盖 → 安装时 hint → `GIT_EXECUTABLE` → `shutil.which` → 从 `GIT_EXEC_PATH` 逐级回溯安装根（同时按 Windows / POSIX 两种分隔符处理）→ `where.exe git` → 常见安装位置 → 兜底 `"git"` |
| `tests/test_pre_commit_git_resolve.py` | 新增 5 条回归：hint 写入、hint 优先、**残缺 PATH + mojibake GIT_EXEC_PATH 下仍能定位 git**、任何环境都不抛异常、反推能走到安装根 |

**验证**：WSL Ubuntu（真实 Linux 语义，非模拟）全量 **537 passed / 11 skipped / 0 failed**；
Windows 全量除 3 个 `test_pandax_serve` 并发 flaky 外全绿（该文件单独跑 20 passed，与本次改动无关）。

### 踩坑留档

- **改完代码必须先跑测试再提交**：v0.7.31.0 首轮 CI 挂在 `tests/conftest.py` 的 `SyntaxError`（docstring 里写了 `r"""` 三引号导致提前闭合）——
  本地没跑测试就提交，白白浪费一轮 CI。
- **Windows 上 `git clone <本地路径>` 不可用**：`git-upload-pack: command not found`
  （Git for Windows 的 `cmd/` 下只有 `git-upload-pack.exe`，没有无后缀的 sh 脚本）——
  连 `--local` 也会调它。所以本仓库**不能用 clone 做本地恢复**，要用 `git --git-dir` 读或直接复制 `objects/refs`。
- **`os.name` 是可以改的**（module 属性）：改完 reload 即可在 Windows 上模拟 POSIX 分支，
  本地就能验跨平台逻辑，不必干等 CI。
  本轮正是靠这个探针抓到了「self 命中就 `break`」导致同目录 `pandaone-mcp` 被漏检的自引入缺陷。

## [0.7.30.0] - 2026-10-25

真机安装 0.7.28.0 后继续实测，又挖出 2 个真 bug。

### Fixed: MCP 靠 PATH 里的裸 `pandaone` 命令调 CLI —— 两个后果

`src/pandaone_mcp/__main__.py` 原本是 `subprocess.run(["pandaone", "--silent"] + args)`：

1. **产品层面**：Windows PATH = 机器级 + 用户级（机器级在前），pip 版 pandaone 常在机器级的
   `Python\Scripts\` 里 -> MCP 会调到**旧版** CLI，出现"MCP 报 11 个工具、实际跑的是旧版本"。
2. **测试层面**：机器上没装 pip 版 `pandaone` 时，MCP 工具整体报 `[WinError 2]`
   （实测挂 4 例：test_call_init / test_call_write / test_call_install_hook / test_call_fingerprint_update）。

修复：新增 `_cli_command()`，不再靠 PATH 猜：
- frozen 形态 -> 调**同目录**的 `pandaone.exe`（MCP 与 CLI 必然同版本）；
- 源码形态 -> `sys.executable -m pandaone`（不依赖任何外部安装）。

### Fixed: `pandaone setup` 的 serve 步骤漏了 frozen 形态感知

`cmd_upgrade.py` 的 `_restart_serve` 在 v0.7.26.0 已经做过形态感知，
但 `cmd_setup.py` 的 `_step_serve` **漏了** —— frozen 形态下
`pandaone.exe -m pandaone serve` 会被当成子命令 -> `invalid choice: '-m'`，
`pandaone setup` 的仪表盘步骤必然失败。同一个坑在 upgrade 修过、setup 没修。

修复：`cmd_setup.py` 新增 `_is_frozen()`，`_step_serve` 按形态构造命令。

### Fixed: 冲突清理漏了 `pandaone-mcp` 入口

`path_conflicts.shadows()` 原本只查 `pandaone` 主命令，漏了**同名**的 `pandaone-mcp.exe`
（pip 版和 exe 版同名）。实测：装完 exe 版后 `where pandaone-mcp` 仍指向
`Python\Scripts\pandaone-mcp.exe`（旧版）。

修复：`shadows()` 同时检查 `CONSOLE_SCRIPT_NAMES + MCP_SCRIPT_NAMES`。
（`pandaone-guard.exe` 连字符 vs exe 版 `pandaone_guard.exe` 下划线 —— 不同名，不冲突。）

### Tests

- `tests/test_cmd_setup_upgrade.py` +5 例：setup serve 的 frozen / 源码两种命令形态、
  MCP `_cli_command()` 的 frozen / 源码两种形态
- 基线：`530 passed, 9 skipped` -> `535 passed, 9 skipped`

## [0.7.28.0] - 2026-10-25

### Fixed: 真机安装实测挖出 —— "用户级 PATH 前置" 治不了机器级抢占

v0.7.27.0 把 `%LOCALAPPDATA%\Pandaone` 前置到了**用户级** PATH 首位。真机装完实测：

```
where pandaone
  C:\Users\Administrator\AppData\Local\Programs\Python\Python311\Scripts\pandaone.exe   <- pip 版 0.7.21.3
  C:\Users\Administrator\AppData\Local\Pandaone\pandaone.exe                              <- exe 版 0.7.27.0
pandaone --version  ->  pandaone v0.7.21.3     <- 仍然是旧版！
```

**根因**：Windows 的 PATH 拼接规则是 **「机器级 PATH + 用户级 PATH，机器级在前」**。
`Python311\Scripts` 在**机器级** PATH 里，用户级前置在机制上**够不着**它。
所以「用户级 PATH 前置」这个方案在真机上根本不成立 —— 必须让机器级那个不再是 `pandaone`。

| 位置 | 改动 |
|---|---|
| 新增 `src/pandaone/path_conflicts.py` | 集中实现冲突判定：只读探测，**绝不执行外部 exe、绝不改文件**。`shadows()` 只返回**排在当前运行目录之前**的 pandaone（排在后面的不会被命中） |
| `src/pandaone/cmd_doctor.py` | 新增 **L8_path_conflict** 检查层（doctor 从 7 层变 8 层），直接点名冲突路径 |
| `src/pandaone/cmd_doctor.py` | 新增 `doctor --clean-conflicts`：把抢占命令的旧 pandaone **改名备份**（`pandaone.exe` → `pandaone.exe.bak-pandaone-<ver>`） |
| `src/pandaone/cmd_setup.py` | 新增 `clean_path_conflicts()` + setup 流程里的「PATH 冲突」步骤（`--no-clean-conflicts` 可关） |
| `src/pandaone/installer/codeaudit.iss` | 安装后自动跑 `doctor --clean-conflicts`（**不能** `skipifsilent` —— 静默安装正是最需要清理的场景） |

**为什么是"改名备份"而不是删除或 `pip uninstall`**：
- 改名：不碰 pip 的包元数据、不删用户文件、**可逆**（改回去即可）；
- 删除：不可逆，删错了没法恢复；
- `pip uninstall`：要机器上有 python + pip，还可能连带影响别的依赖。

### Fixed: 安装器 PATH 前置后的重复项与卸载残留

- `[Registry]` 段改为 `{app};{olddata}`（前置），`[Code]` 段再做一次去重 + 前置兜底（幂等）。
- 新增 `CurUninstallStepChanged` → `RemoveAppFromPath`：卸载时把 `{app}` 从用户 PATH 摘掉，
  否则目录被删后 PATH 里留一行坏路径，敲 `pandaone` 会得到"不是内部或外部命令"。
  **实测**：卸载后 PATH 里 `%LOCALAPPDATA%\Pandaone` 已消失（只剩用户自己的 `pandaone\venv\Scripts`）。
- 安装后广播 `WM_SETTINGCHANGE`（`SendMessageTimeout`），已打开的终端立刻拿到新 PATH。

### Fixed: mock.Mock 的属性陷阱

`getattr(args, 'clean_conflicts', False)` 在 `args` 是 `mock.Mock()` 时会返回 **truthy 的 Mock 对象**，
导致 `doctor` 误入清理分支。改为 `is True` 严格判断，并在测试里显式设置该属性。

### Fixed: 脏指纹残留导致大批无关测试连环失败

`~/.pandaone_fp.txt` 是**跨进程的全局状态**，不是测试产物。判定顺序里
「同版本 + hash 变」= 判篡改 -> CLI 锁死（rc=1），于是：

- 上一次运行留下的记录（版本/hash 与当前源码不符）会让本次运行大批**无关**测试连环失败；
- 上次跑的是 frozen 形态（`form=frozen`）、这次跑源码形态，版本又相同 → 同样锁死。

实测：改完版本号后第一次全量跑挂了 **32 个**（test_e2e / test_export / test_ci 全军覆没），
重跑就全绿 —— 纯脏状态问题，不是代码问题。

修复：`tests/conftest.py` 增加 session 级 autouse fixture，在 session 开始时
把指纹重播种为**当前源码**的正确指纹（`fp_security.save_fp(version, compute_fingerprint())`）。
只在 session 开始做一次（算指纹要扫整个包目录，per-test 太慢）。

**验证**：故意写入脏指纹（`version=0.7.28.0` + `hash=0*64`，按判定逻辑必然锁死），
再跑全量 → `530 passed, 9 skipped` 全绿。

### Added

- i18n 词条 `setup_conflict_none` / `setup_conflict_renamed` / `setup_conflict_partial` /
  `setup_conflict_failed` / `setup_conflict_check_failed`（zh + en）
- i18n 词条 `_doctor_path_conflict` / `_doctor_path_conflict_hint`（zh + en）
- doctor 层级文案 7 层 → 8 层

### Tests

- `tests/test_cmd_setup_upgrade.py` +13 例：PATH 前置语义 4 例、安装器模板静态断言 4 例、
  `path_conflicts` 判定 4 例、`clean_path_conflicts` 改名/可逆/dry-run/无冲突 4 例
- `tests/test_cmd_doctor.py` +5 例：`--clean-conflicts` 参数解析 2 例、默认不触发 1 例、
  清理分支执行 1 例、mock 属性陷阱防护 1 例
- 基线：`513 passed, 9 skipped` → `530 passed, 9 skipped`

## [0.7.27.0] - 2026-10-25

### Fixed: 装完 exe 版却"没生效" —— PATH 被旧 pip 版抢占

真机安装前的环境核查发现（本机实测，非推理）：用户 PATH 里
`C:\Users\Administrator\AppData\Local\Programs\Python\Python311\Scripts\` 排在靠前，
其中装着 pip 版 pandaone 0.7.21.3。而安装器把 `%LOCALAPPDATA%\Pandaone` **追加**到 PATH 末尾
（`{olddata};{app}`），`setup` 命令的 `_persist_path_windows` 同样 `parts.append(...)`。

结果：装完 exe 版后，命令行敲 `pandaone` 仍然命中旧 pip 版 —— 用户体感就是"装了新版没生效"。

| 位置 | 旧行为 | 新行为 |
|---|---|---|
| `installer/codeaudit.iss` `[Registry]` | `{olddata};{app}`（追加末尾） | `{app};{olddata}`（**前置**首位） |
| `installer/codeaudit.iss` `[Code]` | 无 | `CurStepChanged(ssPostInstall)` 做去重 + 前置兜底；`BroadcastEnvChange` 广播 `WM_SETTINGCHANGE`，已打开的终端立刻生效 |
| `installer/codeaudit.iss` `[Code]` | 无 | `CurUninstallStepChanged` → `RemoveAppFromPath`，卸载时摘掉 `{app}`，不留指向已删目录的坏路径 |
| `src/pandaone/cmd_setup.py` `_persist_path_windows` | `parts.append(target)` | `parts.insert(0, target)`，并对"已存在但在中间"的做**前移**而非 skip；大小写 / 尾部反斜杠差异按同一条去重 |
| `src/pandaone/cmd_setup.py` `_persist_path_posix` | 已是前置 `export PATH="{target}:$PATH"` | 不变 —— 这次是把 Windows 侧对齐到 posix 语义 |

跨平台语义原本就不一致：posix 前置、Windows 追加。现在统一为**前置**。

### Added

- i18n 词条 `setup_path_moved`（zh + en，417/417 覆盖）：区分"新增"与"前移"两种结果。

### Tests

- `tests/test_cmd_setup_upgrade.py` +6 例（34 → 40）：
  - PATH 前置到首位、原有项保留、已存在则前移且不重复、大小写/尾斜杠去重、已在首位则 skip
  - 安装器模板静态断言：PATH 行必须是 `{app};{olddata}`（防止改回追加）、
    必须有 `RemoveAppFromPath` / `CurUninstallStepChanged`、必须有 `SendMessageTimeout` 广播
- 基线：`513 passed, 9 skipped` → `518 passed, 9 skipped`

## [0.7.26.0] - 2026-10-24

### Fixed: 「.exe 打包与发布链路验证」沙盒端到端挖出的三个真 bug

用**真正要交付的产物**（`dist/pandaone/pandaone.exe`，即安装后的 `%LOCALAPPDATA%\Pandaone\pandaone.exe`）
在沙盒里跑 setup / upgrade / backup / install-mcp 全链路，挖出 3 个**只在打包形态才会犯**的错：

| # | 现象 | 根因 | 修复 |
|---|---|---|---|
| 1 | `pandaone upgrade` 在 exe 里**必然失败**：`pip 升级失败: pandaone: error: argument command: invalid choice: 'pip'` | `_pip()` 用 `sys.executable -m pip`；frozen 形态下 `sys.executable` 就是 `pandaone.exe` 本身，"pip" 被当成 CLI 子命令 | 新增 frozen 分支：exe 形态不碰 pip，改为在 exe 同目录找 `PandaoneSetup-<版本>-x64.exe`，提示用户或用 `--launch-installer` 直接启动 |
| 2 | `pandaone setup` 的 PATH 步骤是**死代码**：`[WARN] NameError: name '_persist_user_path' is not defined` → 用户装完 exe，命令行里根本没有 `pandaone` | handler 调 `_persist_user_path`，模块里定义的却是 `persist_user_path`（少一个下划线）。每步的 `except Exception` 把 NameError 吞成 WARN，整条 setup 仍 rc=0，单测全绿 | 改回 `persist_user_path`；`_executable_dir()` 改成形态感知（frozen=exe 目录；源码=sysconfig scripts 目录，不是解释器目录）；写完 PATH 广播 `WM_SETTINGCHANGE`，新终端立刻生效 |
| 3 | `_restart_serve` 在 exe 里同样炸（`sys.executable -m pandaone serve`） | 同 #1 | frozen 走 `[exe, "serve", ...]`，源码走 `[python, "-m", "pandaone", "serve", ...]` |

### Added: 发布链路门禁 —— 同版本重打包 = 存量用户集体变砖

- `build_pyinstaller.py` 记录上次成功打包的版本（`.pandaone/release_state.json`），
  **同版本号重打包默认直接拒绝**（`--allow-same-version` 仅限本地验证）。
- 依据（实测，非推理）：frozen 指纹记录 `{version, hash, form}`，**同版本 + hash 变 = 判篡改** →
  所有真命令 rc=1 锁死；抬版本号则自动刷新指纹（实测 0.7.25.0 → 0.7.26.0 自动刷新，rc=0）。
  也就是说：**发布必须抬版本号**，否则装了旧版的用户升级即变砖。
- 注意：`pandaone --version` / `--help` 是 meta 命令，按 v0.7.19 设计**跳过**指纹检查，
  验证篡改锁死必须用真命令（如 `status`）。

### Changed

- `persist_user_path` / `_persist_path_windows` / `_persist_path_posix` 的返回契约统一为
  `(状态, 说明)`，状态 ∈ `ok/skip/warn`，与 handler 的步骤契约一致（此前返回 bool，状态位对不上）。
- `pandaone upgrade` 解析版本号时去掉末尾 0：`0.7.26` 与 `0.7.26.0` 判为同一版本。
- `pandaone upgrade` 在 exe 形态下会明确区分三种情况：已是最新 / 本地版本已新于 PyPI /
  PyPI 有新版但同目录没有安装包（并给出该下载什么文件名）。

### Tests

- `tests/test_cmd_setup_upgrade.py` +14 例：PATH 步骤真的被调用、无 NameError、
  frozen 目录取 exe 目录、frozen 不碰 pip、找不到安装包、找到安装包、`--from-source` 拒绝、
  版本比较、打包守卫（同版本拒绝 / 抬版本放行 / `--allow-same-version` 放行）。
- 全量：**513 passed, 9 skipped**（上一版 499 + 14）。

## [0.7.25.0] - 2026-10-24

### Fixed: 「安装后自动注册 MCP」沙盒端到端挖出的两个真 bug

用**真正要装的那份 frozen exe**（`dist/pandaone/pandaone.exe` == 装完的 `{app}\pandaone.exe`）
在沙盒里跑完整链路（重定向 `APPDATA` / `HOME` 隔离真实 IDE 配置 → 注册 → 读回 → 用配置里写的
那个 command 真握手），实测挖出两个此前单测盖不到的 bug：

| # | 现象 | 根因 | 处置 |
|---|---|---|---|
| 1 | 既有 `mcpServers.pandaone` 条目里用户自己配的 `env`（可能带 API key / `PANDAONE_FP_PASSWORD`）和 `args` 被**整条替换清空** | `install_into()` 里 `servers[SERVER_KEY] = new_entry` 无条件整条覆盖 | 条目照旧更新（command 指向新解析的可执行文件），但 `env`/`args` 改为**合并**——只补缺失键，不删已有键 |
| 2 | 打包形态下写进 IDE 配置的 command 是裸名 `pandaone-mcp`，IDE 启动时 PATH 命中 **pip 装的旧版**（实测握手 `serverInfo.version = 0.7.21.3`，与新装的 0.7.25.0 不符） | `resolve_command()` 先问 `shutil.which()`，而 PATH 里残留着旧版 | frozen 形态**优先锁同目录的绝对路径**；`--absolute-command` 显式绝对模式；安装包任务改为 `install-mcp --client auto --absolute-command` |

### Added: `--client auto` 现在能识别「装了 IDE 但还没配置文件」

原先 `auto` 只认「配置文件已存在」，于是装了 Cursor / Trae 但从没建过 `mcp.json` 的用户
根本注册不到 —— 「装完即用」在这一环断掉。现在补上 IDE 安装目录探测（Claude / Cursor /
Trae / Windsurf），装了就把配置建出来（仍然先备份、损坏 JSON 绝不覆盖）。

### Test

沙盒端到端 12 项断言全过：注册成功、其他 server 保留、既有 env 保留、损坏 JSON 未被覆盖、
备份已生成、配置里写出的 command 能真的握手并返回 **11 个工具**、`serverInfo.version`
与安装的版本一致。

新增 5 个用例（`tests/test_cmd_install_mcp.py`）：env 合并、args 保留、frozen 优先同目录
绝对路径、绝对模式不查 PATH、auto 识别已安装 IDE。

## [0.7.24.0] - 2026-10-24

### Added: 一键部署 / 升级 / 备份 / MCP 注册（对应《建议书》产品建议 1.1–1.5 + 历史欠账项）

| 命令 | 作用 |
|---|---|
| `pandaone setup` | 一键本地部署：Python ≥3.10 检查 → git 探测/引导安装 → PATH 持久化（HKCU，无需管理员）→ git 仓库 + **仓库级** user.name/email + baseline commit → `init` → 看门狗 → 右键菜单 → 仪表盘 → `doctor` 体检。**不设 remote、不推送**；单步失败不中断，最后汇总。 |
| `pandaone upgrade` | pip 升级 → 指纹自动刷新 → 重启看门狗 → 重启仪表盘 → 打印版本对比。支持 `--check-only` / `--from-source` / `--no-restart`。 |
| `pandaone backup` | **纯本地**备份：`--output x.bundle` 生成 git bundle（单文件、跨平台、零依赖可恢复）；`--mirror DIR` 建本地裸仓库镜像；`--status` 只读查看。**不集成 gh、不碰远程。** |
| `pandaone install-mcp` | 探测 Claude Desktop / Cursor / Trae / Windsurf → 写前备份 → **只合并不覆盖**（已有 `mcpServers.pandaone` 保留）→ 装后回读自检 → 提示重启 IDE。支持 `--client auto\|claude\|cursor\|trae\|windsurf\|all` / `--dry-run`。 |
| `pandaone init --with-git` | `init` 检测到当前目录不是 git 仓库时，可用 `--with-git` 一并建仓库并提交 baseline commit。 |

四份安装脚本（`install.sh` / `install.ps1` / `scripts/install.sh` / `scripts/install.ps1`）末尾均已接入
`pandaone install-mcp`，可用 `--skip-mcp` / `-SkipMcp` 跳过。

### Added: Windows 一键安装包（.exe）

- 新增 `build_pyinstaller.py`（重写）：适配当前 `src/` 布局，一次打出
  `pandaone.exe` / `pandaone_guard.exe` / `pandaone-mcp.exe`，并调用 Inno Setup 编译出
  **`PandaoneSetup-<版本>-x64.exe`**。
- 安装包**免管理员权限**（装到 `%LOCALAPPDATA%\Pandaone`），自动加入用户 PATH（HKCU）、
  安装级联右键菜单，并可选勾选注册 MCP server。
- `src/pandaone/installer/codeaudit.iss` 同步修正：右键菜单改为与代码一致的
  `ExtendedSubCommandsKey` 结构（旧的 `SubCommands` 在 HKCU 下 Explorer 静默不显示）、
  去掉 `--trust-default`、修正 Inno Setup 6 不兼容指令、`OutputBaseFilename` 改为
  `PandaoneSetup-<版本>-x64`、简体中文 `.isl` 不存在时自动退回英文向导。

### Changed: L5 指纹覆盖面扩展到整个包目录

指纹不再只覆盖 `.py`：`pandaone/` 与 `pandaone_guard/` 两个包目录下的**全部文件**
（`templates/`、`installer/`、`index.html`、`banner.txt`、`*.ico` …）都纳入计算，
排除 `__pycache__` / `*.pyc` / `.git` 等运行时产物。改名、增删、改内容都会改变指纹。

### Changed: 指纹密码可自定义（默认值仍为 `0000`）

- **默认密码保持 `0000`**（本地单用户零摩擦），用户可自行改密：
  `pandaone --set-fingerprint-password <密码>`（≥4 位）、`--reset-fingerprint-password` 回落默认。
- 优先级：`PANDAONE_FP_PASSWORD` 环境变量 > `~/.pandaone/fp_password` 文件 > 默认 `0000`
  （`PANDAX_FP_PASSWORD` 作为废弃别名保留兼容）。
- 密码比较改走 `hmac.compare_digest`（常量时间，防时序侧信道）；连续输错 5 次锁定 15 分钟，
  `--reset-fingerprint-lock` 可解锁。

### Fixed: 打包态（frozen .exe）的 5 处缺陷

1. **版本号丢失**：frozen 下既无 `pyproject.toml` 也无安装元数据 → `pandaone --version`
   显示 `0.0.0+unknown`。现由打包脚本注入 `_build_info.py`。
2. **指纹锁死**：源码态与冻结态的文件集合不同，指纹必然不同，同版本号会被判成篡改 →
   装完 .exe 第一次运行就全锁。现引入指纹"运行形态"（`source` / `frozen`），
   形态切换按合法部署处理并自动刷新。
3. **L7 误报**：frozen 下找不到 `.github/workflows/audit.yml` → 改为 N/A（CI 配置属于源码仓库）。
4. **L6 查错目录**：审计日志是项目级的，改为一律先查当前工作目录。
5. **子进程解码崩溃**：`taskkill` / `netstat` 在中文 Windows 输出 GBK，`text=True` 按 UTF-8
   解码抛 `UnicodeDecodeError` → 统一 `encoding="utf-8", errors="replace"`。

### Fixed: 右键菜单注册结构

`SubCommands` 级联依赖 `HKLM\...\Explorer\CommandStore`（需管理员），HKCU 注册不进 →
Explorer 静默隐藏整个级联菜单。改为 `ExtendedSubCommandsKey` + `<base>\Shell\<verb>\command`，
真机复验：文件右键 26 个动词、目录右键 34 个动词，均可见 "Pandaone 审计工具 / Audit Tools"。

### Fixed: `cmd_status` 的 L5 指纹误报

旧实现拿裸文本与 hex 比对，v0.7.21.2 指纹 json 化之后**永久误报**。现统一走 `_load_fp()`。

### Fixed: pytest 三连坑（开发期）

`sys.path` 注入顺序、模块顶层 `del sys.modules` 造成模块对象分裂、subprocess 跑陈旧副本 ——
详见 `docs/development.md`。

### Test

`494 passed, 9 skipped, 0 failed`（Python 3.11.9 / Windows 10）。

## [0.7.18] - 2026-10-07

### Changed: 完整测试套件前移到 PR 阶段（测试不再是个装饰品）

**发现**：核对 CI 实际配置时，`lint.yml` 的注释写着

> 完整测试（3 OS × 3 Python = 9 矩阵）在 publish.yml 跑，gate 发布。

这句话里有**两个事实错误**：

1. `publish.yml` 里从来没有 9 矩阵 —— 只有一个 ubuntu + Python 3.10 单跑一次；
2. 更关键的是，`publish` job 的 `needs` 写的是 `[build]`，**不包含 `test`**
   —— 也就是说 pytest 挂了照样把包推上 PyPI。

于是"完整测试"在结构上一直是装饰品，两头都不 gate：

| 阶段 | 跑什么 | 实际 gate 了什么 |
|------|--------|------------------|
| PR（`lint.yml` Smoke Tests） | 3 个测试文件的冒烟 | 只拦住这 3 个文件被改坏 |
| 发版（`publish.yml` test job） | 全量 377 个测试 | **什么都不拦**（不接 `needs`） |

后果：改坏 `tests/` 下其余 40 个文件里任何一个的 PR 都能顺利合进 main，
直到发版那一刻才（可能）被发现 —— 而那时发布流程已经拦不住了。

**这是与 v0.7.16、v0.7.17 同一病根的第三次复发**：验证手段与真实场景脱节，
且从来没有人断言过"这个检查到底 gate 了什么"。前两次分别是
`.pandaone/` 半存在（跳过条件永远不触发）与 editable 冒烟绕开打包路径。

**处置**：

1. `lint.yml` 的 Smoke Tests job（规则集**必需**状态检查）新增一步
   **完整测试套件** —— 改坏任何一个测试的 PR 在合并前就被拦住。
   本地实测：editable 安装 / Python 3.11 下 `364 passed, 13 skipped`，约 73 秒
   （job timeout 相应从 5 分钟放宽到 15 分钟）。
2. `publish.yml` 的 `publish` job 改为 `needs: [build, test]`，
   让发版前的那次全量运行真正能拦住"带着失败测试发版"。

**排除项说明**（有据，不是迷信）：`tests/test_watchdog.py` 与
`tests/test_watchdog_dedupe.py` 使用线程 + 时序断言，在共享 runner 上会偶发挂住
（源自 commit `541d50c`「exclude hang-prone watchdog/serve tests」），继续排除，
仍由本地全量回归覆盖（本地跑含这两个文件是 377P/13S/0F）。
同时清掉 `--ignore=tests/test_pandaone_serve.py` —— 该文件早已改名为
`test_pandax_serve.py`，这条参数近年来一直指向一个不存在的文件。

### Fixed: `pandaone log --rejected` 补上「当时想写什么」（死翻译接线）

新关卡第一次运行就抓到的真 bug —— 也正是"完整测试前移"这件事价值的直接证据。

`tests/test_e2e.py::test_full_workflow_e2e` 断言 `log --rejected` 的输出里
要有 `attempted` / `尝试` 字段，在 CI 上一直是**失败**的。原因是：

- 审计记录在写入被拒时**确实保存**了 `attempted_reason` / `attempted_problem` /
  `attempted_approach`（`part_003` 的 REJECTED 分支）；
- 翻译 key `log_attempted` 也**确实定义**在 i18n 双语包里；
- 但 `_print_log` **从来没有调用过它** —— 这是一条**死翻译**。

后果对审计产品是实质缺陷：被拒绝的写入只留一句"为什么拒绝"，不留"当时想写什么"。
审计留痕最关键的那一半丢了 —— 事后复盘能看到"这次被拦了"，却看不到"被拦的是什么"。

**它是怎么藏这么久的**（两头都看不见）：

| 环境 | 表现 |
|------|------|
| CI（非 root runner） | 测试真实执行并**失败**，但 `publish.yml` 的 test job 不接 `needs`，失败既不阻塞发布也无人查看 |
| 本地（root） | 测试因 `euid == 0` 被 `_ROOT_SKIP` **静默跳过**，永远绿 |

修复后普查：i18n 300 个 key 中"定义了但源码从未引用"的死翻译数量 **1 → 0**。

> 顺带说明：i18n 覆盖率检查报 100%，指的是**语言包之间对齐**，它不检查
> "这个 key 到底有没有被用"。所以死翻译能在 100% 覆盖率的保护下一直藏着。

## [0.7.17] - 2026-10-07

### Added: CI 真实安装冒烟关卡（防「装上了跑不起来」复发）

**动机**：v0.7.14 的致命缺陷是用户 `pip install` 之后 CLI 跑不起来。复盘发现 CI 里
唯一的冒烟用的是 **editable 安装**（`pip install -e .`）——它直接从源码目录 import，
**绕开整个 wheel 打包路径**，因此 package-data 漏配、入口点写错、子包没打进 wheel
这几类问题在结构上永远不可能被 editable 冒烟发现。CI 全程绿，用户第一分钟就崩。

**处置**：在 `lint.yml` 的 Smoke Tests job（仓库规则集的必需状态检查）里补一步
**非 editable 真实安装**：

```
python -m venv … && pip install .   # 真正走 wheel
pandaone --help                      # CLI 可执行
command -v pandaone-mcp              # MCP 入口点在
已装版本 == pyproject 声明版本        # 版本漂移
```

这一步复现的就是真实用户的第一分钟，且因为挂在必需检查上，**装坏了就合不进 main**。

### Changed: `pandax-guard` 弃用声明

PyPI 上的旧包名 **`pandax-guard` 已弃用**（停在 0.7.4，不再更新也不再修 bug）。
README 中英文双语顶部均加入醒目提示，并给出迁移命令：

```bash
pip uninstall pandax-guard && pip install pandaone-guard
```

避免新用户搜到旧包装上，得到一份 2026-09 的、带已知缺陷的实现。

## [0.7.16] - 2026-10-07

### Fixed: unlock 不再把受保护文件变成 world-writable（安全缺陷）

**问题**：`unlock` 用 `mode | S_IWUSR | S_IWGRP | S_IWOTH` 解除只读，把 444 解成 **666** —— 门禁自己给同机任意用户开了写后门。而 `lock` 会清除全部三种写位，原始权限就此丢失，解锁时无从还原。

**修复**（`src/pandaone/cli_chunks/part_003.py`）：

| 场景 | 行为 |
|------|------|
| lock | 上锁前把每个文件的原始 mode 记入 `.pandaone/lock_modes.json` |
| unlock（有记录） | 精确还原锁定前的 mode（644 → lock 444 → unlock 644） |
| unlock（无记录，旧版 lock / 手工 chmod） | 只恢复属主写位，绝不补 group/other（默认 644） |
| write 通道临时解锁 | 由 `\|USER\|GROUP\|OTHER` 收窄为只加 `S_IWUSR`，缩短 world-writable 暴露窗口 |

`.pandaone/lock_modes.json` 随 unlock 完成后清理，避免陈旧记录影响后续轮次。

新增两条回归测试：精确还原 644、无记录退化为属主可写。

## [0.7.15] - 2026-10-04

### 主题：AI Agent 真实体验修复 —「装上就能用，接上就干净」

**背景**：GitHub 下载量 22 次 / 0 star / main CI 红。逐条复盘真实使用链路（pip install → MCP 接入 → 日常调用）后，发现的问题不在宣传的功能列表里，而在**第一次真实调用**上。本版本全部围绕「让 MCP 客户端和脚本拿到的输出干净、让 CLI 直调不失效」。

### Fixed: CLI 直接运行静默 no-op（致命）

`cli.py` 是 loader，通过 `exec()` 把 `cli_chunks/part_001-006.py` 编译进同一命名空间，但 exec 时把 `__name__` 覆写为 `"pandaone.cli"`，导致 `python cli.py` 的 `if __name__ == "__main__"` 永假——**直接运行 CLI 什么都不发生，exit code 0**。保存 `_is_main` 标记修复。这是比任何功能缺陷都严重的一类 bug：用户装完第一次敲命令就哑火。

### Fixed: MCP 输出三重噪音（ANSI 转义 + banner + roadmap）

MCP server 通过 subprocess 调 CLI 再回传 stdout，此前把 40+ 行彩色 banner、README 摘要、roadmap 一起塞给 MCP 客户端，污染模型上下文。修复：

- `_run_cli` 统一加 `--silent`，并用 `_strip_ansi()` 剥离 ANSI 转义序列
- CLI 的 banner / README 摘要改为**仅 TTY 输出**（`sys.stdout.isatty()` 门控）——人类在终端仍能看到完整 banner，管道和 MCP 拿到的只有结果

### Added: write 审计通道支持新建文件

此前 `write` 对不存在的文件直接 REJECTED（"目标文件不存在"），Agent 无法通过审计通道创建任何新文件。现在：提供 `--content` + 受保护扩展名即可创建，父目录自动补建，审计记录标注 `"action": "create"`。

### Fixed: 只读检测在 root 下失效

`os.access(path, os.W_OK)` 对 root 恒返回 True，导致 L1 锁（444 文件）对 root 不设防。改为直接检查权限位 `st_mode & S_IWUSR`。（注：OS 层面 root 物理上不受权限位约束，本修复保证 CLI 审计层行为一致；相关测试在 root 环境标记 skip。）

### Improved: log / status 输出补全

- `log` 打印此前为死代码的记录头（ID / 时间 / agent），字段标签本地化，新增 `Lines: +N -M` 与 Diff 面板（verbose 不截断）
- `status` 补 L2 watchdog 区块（`os.kill(pid, 0)` 探活）与未 init 提示；计数标签本地化
- `log` / `export` 未 init 时给出明确提示而非空输出

### Fixed: MCP server 版本漂移

`pandaone_mcp` 硬编码 `__version__ = "0.7.7"`，与实际包版本（0.7.14+）脱节 7 个版本。改为动态解析 `pandaone.__version__`，`serverInfo` 同步。

### Fixed: 测试套件可移植性（CI 红的直接原因）

- 5 个测试文件硬编码作者机器路径（`D:\软件\Git\cmd\git.exe`）→ `shutil.which("git")` 动态探测
- 2 个静态分析测试读 `cli.py`（loader）而非 `cli_chunks/` → 修正读取方式
- `test_audit_i18n_ci.py` 的 `fresh_cli` fixture 从 `git show HEAD` 恢复文件，会**静默回滚开发者未提交的修改**（本次开发中实际吃掉过一次修复）→ 改为备份工作区状态
- install-git 测试的输出长度阈值按英文硬编码（>50），i18n 中文输出（38 字符）必挂 → 对齐为 >20
- 权限类测试在 root 环境标记 skip（环境限制，非产品缺陷）

### Fixed: 安装包缺文件

`pyproject.toml` 补 `[tool.setuptools.package-data]`：`installer/windows/*.ps1`、`installer/macos/*.sh`、`installer/linux/*.sh` 随包分发，修复安装后右键菜单脚本缺失。

## [0.7.14-hotfix1] - 2026-09-21

### Fixed: 右键菜单子项不可见（ExtendedSubCommandsKey 迁移）

Win11 22H2+ 右键能看到 Pandaone 但展开看不到 4 个子项。原脚本用 MUIVerb + SubCommands (V1) 与 Win11 资源管理器渲染逻辑不兼容。

迁移到微软官方推荐的 ExtendedSubCommandsKey (V2)：父菜单 (Default) 改为空字符串（V2 强制）；删除 MUIVerb/SubCommands；4 个 verb 搬到独立 Shell\ 子键；3 个入口共享命令仓库（注册表 -51%）；Init 加 CommandFlags=0x20 视觉分隔。最低 Win10 1809。

顺手修复 SetRegValue 对 DWord/Binary 不支持（PS5.1 把 0x20 推断为 long），该隐患从 v0.7.x 就存在，本次因 CommandFlags 首次暴露。

新增 test_registry.bat / .ps1 / _real.bat 三个回归测试。

实战报告：`实战验证报告_v0.7.14_右键菜单修复.md`。

## [0.7.14] - 2026-09-16

### M8ven Trust Index A 级 — Verified Publisher

**用户旅程**：「用户能在 GitHub 上面下载就能用的」原则延伸到「AI Agent 生态可信」层面。

v0.7.14 是 v0.7.13 后**两天内的快速迭代**，核心目标是：

1. **通过 M8ven Trust Index 全量审查**
2. **修复 M8ven 公开 finding 中的 1 个 hard blocker**
3. **让 README 在 GitHub 首屏 5 秒内传达产品价值**

### Added: MCP 工具 annotations 全量声明（PR #44）

**问题（M8ven 公开 finding）**：
- 11 个 MCP 工具 **全部**缺失 4 个 MCP spec 要求的 hints（readOnlyHint / destructiveHint / idempotentHint / openWorldHint）
- OpenAI 目录**直接拒绝收录**缺少任一 hint 的工具
- 这是 OpenAI 目录合规的硬性要求，不是软建议

**修复**（`src/pandaone_mcp/__main__.py`）：

| 工具 | readOnly | destructive | idempotent | openWorld | 行为依据 |
|---|---|---|---|---|---|
| `pandaone_init` | F | F | F | F | 创建 `.pandaone/`，每次运行变更状态 |
| `pandaone_lock` | F | F | T | F | 改 attrs；可逆；锁两次=锁一次 |
| `pandaone_unlock` | F | F | T | F | 锁的反操作；同样幂等 |
| `pandaone_write` | F | **T** | F | F | 覆盖文件内容；每次追加审计记录 |
| `pandaone_log` | **T** | F | T | F | 只读查询 |
| `pandaone_status` | **T** | F | T | F | 只读查询 |
| `pandaone_install_hook` | F | F | T | F | 写 `.git/hooks/pre-commit`；幂等 |
| `pandaone_watch` | F | F | F | F | 启动守护进程；不幂等 |
| `pandaone_install_git` | F | F | T | **T** | 从 GitHub Releases 下载便携 git |
| `pandaone_fingerprint_update` | F | F | T | F | 写哈希；同密码→同状态 |
| `pandaone_ci` | **T** | F | T | F | 纯校验；不改仓库 |

**配套测试**（`tests/test_mcp_server.py`）：

- `test_each_tool_has_annotations` — schema 验证，确保每个工具有 4 个 hints 都是 bool
- `test_call_install_hook_creates_precommit` — 验证 hook 文件被写入
- `test_call_install_git_probe_only_safe` — 验证不触发下载
- `test_call_fingerprint_update_writes_hash` — 使用默认密码 `0000`（CLI 默认值）
- `test_call_ci_reachable_returns_verification` — 验证 MCP wrapper 在 base 不存在时不崩溃

测试结果：**89 passed (was 84)** · 11/11 工具覆盖（was 7/11 = 64%）

### Added: README 视觉冲击升级（PR #43）

**问题**：README 首屏只有 ASCII 框 + 徽章，新访客 5 秒内**看不出** pandaone 是干嘛的。

**修复**：在 4 个战略位置嵌入真实截图：

| 位置 | 截图 | 视觉作用 |
|---|---|---|
| 第 11-15 行（顶部 logo 下方） | `terminal-write.png` | 首屏直接看到 `[APPROVED]` 凭证 |
| 查看审计日志 章节 | `terminal-log.png` | 展示 reason/problem/approach 三段式凭证 |
| 项目状态仪表盘 章节 | `terminal-status.png` | 41 保护格式 + L1/L6 实时状态 |
| Web