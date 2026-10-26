#!/usr/bin/env bash
# ============================================================
# Pandaone AI Agent 一键硬隔离安装 + 环境自动配置脚本 (macOS / Linux)
# ============================================================
#
# 第一性原理:
#   - "硬隔离" = 强制 venv, 不允许 pip install 到 system / user site-packages
#   - venv 路径固定到 ~/.local/share/pandaone/venv (XDG 标准), 与 wheel 同目录
#   - wheel 源永远从 GitHub API 拉最新 release (不硬编码 URL, 不从 PyPI 拉)
#   - 自动把 venv/bin 加到 PATH (shell rc 持久化)
#   - **v0.7.12**: 默认还会自动配置 git pre-commit hook (仅当 cwd 是 git repo)
#     用户需求: "GitHub 安装后所有环境都自动配置好"
#     (macOS/Linux 没有 Windows 右键菜单的概念, 所以只做 hook)
#
# 对抗式审查:
#   - 不支持 pip install --user 兜底 (硬隔离承诺不能开后门)
#   - 不依赖 pipx (用户机器可能没装, 多一个依赖)
#   - 不从 PyPI 拉 (用户明确要 "GitHub 下载")
#   - 已存在 venv 时直接复用 (升级而非重建)
#   - hook 安装只在当前 git repo 内, 不污染其他 repo (per-repo scope)
#
# 用法:
#   # 默认: 装最新版 + 自动配置 git hook (cwd 是 git repo 时)
#   curl -sSL https://raw.githubusercontent.com/hellob1889/Pandaone-AI-Agent/main/install.sh | bash
#
#   # 装指定版本
#   bash install.sh --version v0.7.12
#
#   # 装本地 wheel (开发/调试用)
#   bash install.sh --wheel-path /path/to/pandaone_guard-0.7.12-py3-none-any.whl
#
#   # 只装 pandaone, 不配置 git hook
#   bash install.sh --skip-hook
#
set -euo pipefail

REPO_OWNER="hellob1889"
REPO_NAME="Pandaone-AI-Agent"
GITHUB_API="https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}"

# XDG Base Directory Standard
INSTALL_ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/pandaone"
VENV_DIR="${INSTALL_ROOT}/venv"
WHEEL_CACHE_DIR="${INSTALL_ROOT}/wheels"

# ---- ANSI color helpers ----
if [ -t 1 ]; then
    C_CYAN='\033[36m'; C_GREEN='\033[32m'; C_YELLOW='\033[33m'; C_RED='\033[31m'; C_RESET='\033[0m'
else
    C_CYAN=''; C_GREEN=''; C_YELLOW=''; C_RED=''; C_RESET=''
fi
step() { printf "${C_CYAN}▶ %s${C_RESET}\n" "$1"; }
ok()   { printf "${C_GREEN}✓ %s${C_RESET}\n" "$1"; }
warn() { printf "${C_YELLOW}⚠ %s${C_RESET}\n" "$1"; }
err()  { printf "${C_RED}✗ %s${C_RESET}\n" "$1"; }

# ---- Parse args ----
VERSION=""
WHEEL_PATH=""
FORCE=0
SKIP_HOOK=0
SKIP_MCP=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --version)    VERSION="$2"; shift 2 ;;
        --wheel-path) WHEEL_PATH="$2"; shift 2 ;;
        --force)      FORCE=1; shift ;;
        --skip-hook)  SKIP_HOOK=1; shift ;;
    --skip-mcp)   SKIP_MCP=1; shift ;;
        -h|--help)
            sed -n '2,30p' "$0"; exit 0 ;;
        *) err "Unknown arg: $1"; exit 1 ;;
    esac
done

# ---- 1. 检测 Python ----
step "Detecting Python..."
PY=""
for cmd in python3 python py; do
    if command -v "$cmd" >/dev/null 2>&1; then
        if "$cmd" -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" 2>/dev/null; then
            V=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
            PY="$cmd"
            ok "Python $V ($cmd)"
            break
        fi
    fi
done
if [ -z "$PY" ]; then
    err "Python ≥ 3.8 not found."
    echo "  macOS: brew install python3"
    echo "  Ubuntu/Debian: sudo apt install python3 python3-venv"
    echo "  Fedora: sudo dnf install python3"
    echo "  Arch: sudo pacman -S python python-pip"
    exit 1
fi

# ---- 1.5. v0.7.13: 检测 Git (友好提示, 不自动装) ----
if command -v git >/dev/null 2>&1; then
    GIT_VER=$(git --version)
    ok "Git: $GIT_VER"
else
    warn "git not found in PATH"
    echo "  For git pre-commit hook, install git:"
    case "$OSTYPE" in
        darwin*)
            echo "    xcode-select --install"
            echo "    or: brew install git"
            ;;
        linux*)
            if command -v apt >/dev/null 2>&1; then
                echo "    sudo apt install git"
            elif command -v dnf >/dev/null 2>&1; then
                echo "    sudo dnf install git"
            elif command -v yum >/dev/null 2>&1; then
                echo "    sudo yum install git"
            elif command -v pacman >/dev/null 2>&1; then
                echo "    sudo pacman -S git"
            elif command -v apk >/dev/null 2>&1; then
                echo "    sudo apk add git"
            fi
            ;;
    esac
    echo "  (No git = no auto pre-commit hook. Install git later and re-run install.sh.)"
    echo ""
fi

# ---- 2. 创建隔离目录结构 ----
step "Creating isolation layout at $INSTALL_ROOT..."
mkdir -p "$INSTALL_ROOT" "$WHEEL_CACHE_DIR"

# ---- 3. 决定 wheel 源 ----
WHEEL_FILE=""
if [ -n "$WHEEL_PATH" ]; then
    # 用户指定本地 wheel
    if [ ! -f "$WHEEL_PATH" ]; then
        err "Local wheel not found: $WHEEL_PATH"
        exit 1
    fi
    WHEEL_FILE=$(cp "$WHEEL_PATH" "$WHEEL_CACHE_DIR/" && echo "$WHEEL_CACHE_DIR/$(basename "$WHEEL_PATH")")
    ok "Using local wheel: $(basename "$WHEEL_FILE")"
else
    # 从 GitHub API 拉最新 release 的 wheel URL
    step "Fetching latest release from GitHub..."
    if [ -n "$VERSION" ]; then
        API_URL="${GITHUB_API}/releases/tags/${VERSION}"
    else
        API_URL="${GITHUB_API}/releases/latest"
    fi

    RELEASE_JSON=""
    if command -v curl >/dev/null 2>&1; then
        RELEASE_JSON=$(curl -sSL -H "Accept: application/vnd.github+json" "$API_URL")
    elif command -v wget >/dev/null 2>&1; then
        RELEASE_JSON=$(wget -qO- --header="Accept: application/vnd.github+json" "$API_URL")
    else
        err "Neither curl nor wget found"
        exit 1
    fi

    RELEASE_TAG=$(echo "$RELEASE_JSON" | python3 -c "import sys, json; print(json.load(sys.stdin).get('tag_name', ''))" 2>/dev/null || echo "")
    if [ -z "$RELEASE_TAG" ]; then
        err "Failed to parse release JSON"
        exit 1
    fi
    ok "Release: $RELEASE_TAG"

    # 找 .whl asset (用 python 解析 JSON, 比 grep/sed 可靠)
    WHEEL_INFO=$(echo "$RELEASE_JSON" | python3 -c "
import sys, json
r = json.load(sys.stdin)
for a in r.get('assets', []):
    if a['name'].endswith('.whl'):
        print(f\"{a['browser_download_url']}|{a['name']}|{a['size']}|{a.get('digest', '').replace('sha256:', '')}\")
        break
")
    WHEEL_URL=$(echo "$WHEEL_INFO" | cut -d'|' -f1)
    WHEEL_NAME=$(echo "$WHEEL_INFO" | cut -d'|' -f2)
    WHEEL_SIZE=$(echo "$WHEEL_INFO" | cut -d'|' -f3)
    EXPECTED_SHA=$(echo "$WHEEL_INFO" | cut -d'|' -f4)

    if [ -z "$WHEEL_URL" ]; then
        err "No .whl asset found in release $RELEASE_TAG"
        exit 1
    fi

    WHEEL_FILE="${WHEEL_CACHE_DIR}/${WHEEL_NAME}"

    # 复用缓存 (如果 SHA256 一致)
    if [ -f "$WHEEL_FILE" ] && [ "$FORCE" -eq 0 ]; then
        ACTUAL_SHA=$(sha256sum "$WHEEL_FILE" | awk '{print $1}')
        if [ "$ACTUAL_SHA" = "$EXPECTED_SHA" ]; then
            ok "Wheel already cached: $WHEEL_NAME"
        else
            warn "Cached wheel SHA256 mismatch, re-downloading"
            rm -f "$WHEEL_FILE"
        fi
    fi
    if [ ! -f "$WHEEL_FILE" ]; then
        step "Downloading $WHEEL_NAME ($WHEEL_SIZE bytes)..."
        curl -sSL -o "$WHEEL_FILE" "$WHEEL_URL"
        ACTUAL_SHA=$(sha256sum "$WHEEL_FILE" | awk '{print $1}')
        if [ "$ACTUAL_SHA" != "$EXPECTED_SHA" ]; then
            err "SHA256 mismatch!"
            echo "  expected: $EXPECTED_SHA" >&2
            echo "  actual:   $ACTUAL_SHA"   >&2
            exit 1
        fi
        ok "SHA256 verified: $ACTUAL_SHA"
    fi
fi

# ---- 4. 创建/复用 venv ----
if [ -d "$VENV_DIR" ]; then
    step "Reusing existing venv at $VENV_DIR"
else
    step "Creating venv at $VENV_DIR..."
    "$PY" -m venv "$VENV_DIR"
    ok "venv created"
fi

VENV_PY="${VENV_DIR}/bin/python"
VENV_PIP="${VENV_DIR}/bin/pip"

# ---- 5. pip install 到 venv (不碰任何 site-packages) ----
step "Installing $(basename "$WHEEL_FILE") into venv..."
"$VENV_PY" -m pip install --quiet --upgrade pip
"$VENV_PY" -m pip install --quiet --upgrade "$WHEEL_FILE"
ok "Installed in venv"

# ---- 6. 把 venv/bin 加到 PATH (shell rc 持久化) ----
VENV_BIN="${VENV_DIR}/bin"
EXPORT_LINE="export PATH=\"${VENV_BIN}:\$PATH\""

# 检测用户的 shell rc
SHELL_RC=""
case "${SHELL:-/bin/bash}" in
    */zsh)  SHELL_RC="$HOME/.zshrc" ;;
    */bash) SHELL_RC="$HOME/.bashrc" ;;
    */fish) SHELL_RC="$HOME/.config/fish/config.fish" ;;
    *)      SHELL_RC="$HOME/.profile" ;;
esac

if [ -n "$SHELL_RC" ]; then
    if ! grep -qF "$VENV_BIN" "$SHELL_RC" 2>/dev/null; then
        step "Adding $VENV_BIN to $SHELL_RC..."
        printf '\n# pandaone-guard (added by install.sh)\n%s\n' "$EXPORT_LINE" >> "$SHELL_RC"
        ok "PATH updated (run 'source $SHELL_RC' or restart shell)"
    else
        ok "$VENV_BIN already in $SHELL_RC"
    fi
fi

# ---- 7. 验证 ----
step "Verifying..."
VERSION_OUTPUT=$("$VENV_PY" -m pandaone --version 2>&1)
ok "$VERSION_OUTPUT"

IMPORTED_VER=$("$VENV_PY" -c "import importlib.metadata; print(importlib.metadata.version('pandaone-guard'))")
ok "importlib.metadata.version = $IMPORTED_VER"

# ---- 8. 自动配置 git pre-commit hook (仅当 cwd 是 git repo + git 可用) ----
if [ "$SKIP_HOOK" -eq 0 ] && ! command -v git >/dev/null 2>&1; then
    printf "${C_YELLOW}[SKIP] git hook (git not installed)${C_RESET}\n"
fi
if [ "$SKIP_HOOK" -eq 0 ] && command -v git >/dev/null 2>&1; then
    # 从 cwd 向上找 .git 目录 (进入 git repo 边界)
    GIT_ROOT=""
    CHECK_DIR="$(pwd)"
    while [ -n "$CHECK_DIR" ]; do
        if [ -d "$CHECK_DIR/.git" ]; then
            GIT_ROOT="$CHECK_DIR"
            break
        fi
        PARENT="$(dirname "$CHECK_DIR")"
        if [ "$PARENT" = "$CHECK_DIR" ]; then break; fi
        CHECK_DIR="$PARENT"
    done
    if [ -n "$GIT_ROOT" ]; then
        step "Configuring git pre-commit hook in $GIT_ROOT ..."
        if "$VENV_PY" -m pandaone --silent --trust-default install-hook 2>&1; then
            ok "Git pre-commit hook installed in $GIT_ROOT"
        else
            warn "Git hook install failed (exit=$?)"
            echo "       You can retry later: pandaone install-hook"
        fi
    else
        printf "${C_YELLOW}[INFO] cwd is not in a git repo, skipping git hook${C_RESET}\n"
        echo "       (cd to a git repo and run: pandaone install-hook)"
    fi
else
    printf "${C_YELLOW}[SKIP] git hook (per --skip-hook)${C_RESET}\n"
fi

# ---- 9. 注册 MCP server（可用 --skip-mcp 跳过）----
if [[ "$SKIP_MCP" -eq 0 ]]; then
    printf "${C_CYAN}[9/10] 注册 MCP server 到 IDE 配置（Claude Desktop / Cursor / Trae）...${C_RESET}\n"
    if "$VENV_BIN/pandaone" install-mcp --client auto; then
        printf "${C_GREEN}[OK] MCP server 注册完成${C_RESET}\n"
    else
        printf "${C_YELLOW}[WARN] MCP 注册失败，可稍后手动执行: pandaone install-mcp${C_RESET}\n"
    fi
else
    printf "${C_YELLOW}[SKIP] MCP 注册 (per --skip-mcp)${C_RESET}\n"
fi

# ---- 10. 提示下一步 ----
echo ""
printf "${C_CYAN}═══════════════════════════════════════════════════${C_RESET}\n"
printf "${C_GREEN} Installation complete!${C_RESET}\n"
printf "${C_CYAN}═══════════════════════════════════════════════════${C_RESET}\n"
echo ""
printf "${C_CYAN}安装位置 / Install location:${C_RESET}\n"
echo "  venv:  $VENV_DIR"
echo "  wheel: $WHEEL_FILE"
echo ""
printf "${C_CYAN}下一步 / Next steps (新开终端 / new terminal):${C_RESET}\n"
echo "  pandaone doctor              # 环境检查"
echo "  pandaone install-hook        # 安装 git pre-commit hook"
echo "  pandaone install-mcp         # 注册 MCP server 到 IDE (Claude/Cursor/Trae)"
echo "  pandaone --help              # 全部命令"
echo ""
printf "${C_CYAN}升级 / Upgrade:${C_RESET}\n"
echo "  curl -sSL https://raw.githubusercontent.com/${REPO_OWNER}/${REPO_NAME}/main/install.sh | bash"
echo ""
printf "${C_CYAN}完全卸载 / Uninstall:${C_RESET}\n"
echo "  rm -rf '$INSTALL_ROOT'"
echo "  # 然后手动从 $SHELL_RC 移除 $VENV_BIN"
