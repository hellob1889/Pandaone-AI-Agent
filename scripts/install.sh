#!/usr/bin/env bash
# install.sh — Pandaone AI Agent 一键安装脚本（macOS / Linux）
# =====================================================
# 按"对抗式审查"：克隆项目后第一次运行，确保环境就位。
#
# 功能：
#   1. 检测 Python 版本（≥ 3.10）
#   2. 探测 git
#   3. 卸载 site-packages 里可能存在的老 pandaone 版本
#   4. python -m pip install -e .（本地源码，--user）
#   5. 验证 pandaone 可用
#   6. 调用 doctor.py 给出最终诊断
#
# 用法：
#   ./scripts/install.sh                # 完整安装
#   ./scripts/install.sh --skip-install # 只诊断
#   ./scripts/install.sh --force        # 全自动（无交互）
#   ./scripts/install.sh --help         # 帮助
#
# 第一性原理：
#   - 用户体验：clone → 1 命令 → 能用
#   - 不假定环境（git/Python/pip 怎么叫、用户级还是系统级）
#   - 失败给清晰提示，不要静默退出

set -euo pipefail

# ============================================================
# 配置
# ============================================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
MIN_PYTHON_MAJOR=3
MIN_PYTHON_MINOR=10

# 颜色
if [[ -t 1 ]] && [[ -z "${NO_COLOR:-}" ]]; then
    C_OK='\033[92m'
    C_WARN='\033[93m'
    C_FAIL='\033[91m'
    C_INFO='\033[94m'
    C_RESET='\033[0m'
else
    C_OK=''; C_WARN=''; C_FAIL=''; C_INFO=''; C_RESET=''
fi

# ============================================================
# 参数解析
# ============================================================
SKIP_INSTALL=0
SKIP_DOCTOR=0
SKIP_MCP=0
FORCE=0
SHOW_HELP=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-install) SKIP_INSTALL=1; shift ;;
        --skip-doctor)  SKIP_DOCTOR=1; shift ;;
    --skip-mcp)     SKIP_MCP=1; shift ;;
    --skip-mcp)     SKIP_MCP=1; shift ;;
        --force)        FORCE=1; shift ;;
        --help|-h)      SHOW_HELP=1; shift ;;
        *) echo "Unknown option: $1"; exit 2 ;;
    esac
done

if [[ "$SHOW_HELP" -eq 1 ]]; then
    cat <<EOF
用法: ./scripts/install.sh [options]

选项:
  --skip-install   跳过 pip install，只跑 doctor
  --skip-doctor    跳过 doctor 验证
  --force          全自动（无交互）
  --help, -h       显示此帮助

示例:
  ./scripts/install.sh                # 完整安装
  ./scripts/install.sh --skip-install # 只诊断
  ./scripts/install.sh --force        # 无交互
EOF
    exit 0
fi

# ============================================================
# 工具函数
# ============================================================
banner() {
    echo -e "${C_INFO}================================================================${C_RESET}"
    echo -e "${C_INFO} Pandaone 一键安装 — install.sh${C_RESET}"
    echo -e "${C_INFO} 仓库: $REPO_ROOT${C_RESET}"
    echo -e "${C_INFO}================================================================${C_RESET}"
    echo ""
}

step() { echo -e "\n${C_INFO}[STEP] $1${C_RESET}"; }
ok()   { echo -e "  ${C_OK}[OK]${C_RESET}   $1"; }
warn() { echo -e "  ${C_WARN}[WARN]${C_RESET} $1"; }
fail() { echo -e "  ${C_FAIL}[FAIL]${C_RESET} $1"; }
info() { echo -e "  ${C_INFO}[INFO]${C_RESET} $1"; }

confirm() {
    if [[ "$FORCE" -eq 1 ]]; then
        return 0
    fi
    local prompt="$1"
    local default="${2:-N}"
    read -p "$prompt" answer
    answer="${answer:-$default}"
    [[ "$answer" =~ ^[Yy] ]]
}

# ============================================================
# 检查函数
# ============================================================
find_python() {
    step "1/6 检测 Python 版本"
    for cmd in python3 python; do
        if command -v "$cmd" >/dev/null 2>&1; then
            local ver
            ver=$("$cmd" --version 2>&1 | head -n1)
            if [[ "$ver" =~ Python[[:space:]]([0-9]+)\.([0-9]+)\.([0-9]+) ]]; then
                local major="${BASH_REMATCH[1]}"
                local minor="${BASH_REMATCH[2]}"
                if [[ "$major" -ge "$MIN_PYTHON_MAJOR" && "$minor" -ge "$MIN_PYTHON_MINOR" ]]; then
                    ok "$ver（≥ $MIN_PYTHON_MAJOR.$MIN_PYTHON_MINOR）"
                    echo "$cmd"
                    return 0
                else
                    warn "$ver（需要 ≥ $MIN_PYTHON_MAJOR.$MIN_PYTHON_MINOR）"
                fi
            fi
        fi
    done
    fail "未找到 Python ≥ $MIN_PYTHON_MAJOR.$MIN_PYTHON_MINOR"
    info "macOS:  brew install python@$MIN_PYTHON_MAJOR.$MIN_PYTHON_MINOR"
    info "Linux:  sudo apt install python3-pip  (Debian/Ubuntu)"
    info "        sudo yum install python3-pip  (RHEL/CentOS)"
    info "或从 https://www.python.org/downloads/ 下载"
    return 1
}

find_git() {
    step "2/6 探测 git"
    if command -v git >/dev/null 2>&1; then
        ok "git: $(command -v git)"
        return 0
    fi
    fail "未找到 git"
    info "macOS:  brew install git"
    info "Linux:  sudo apt install git  /  sudo yum install git"
    info "或: https://git-scm.com/download/"
    return 1
}

uninstall_stale_pandaone() {
    step "3/6 卸载 site-packages 里的老 pandaone"
    if pip show pandaone >/dev/null 2>&1; then
        warn "检测到 site-packages 里装了 pandaone（旧 wheel）"
        local ver
        ver=$(pip show pandaone 2>/dev/null | grep "^Version:" | awk '{print $2}')
        info "version: $ver"
        if confirm "        卸载? (y/N, 默认 y) " "y"; then
            pip uninstall pandaone -y >/dev/null 2>&1 && ok "卸载完成" || warn "卸载失败（可能不影响，继续）"
        else
            info "保留老版本（你将承担版本冲突风险）"
        fi
    else
        ok "未装老 pandaone"
    fi
}

install_pandaone_editable() {
    step "4/6 安装本地源码 pandaone（editable）"
    info "cd $REPO_ROOT"
    cd "$REPO_ROOT"

    # --user 避免需要 sudo（大多数情况下 ~/.local/ 已配置好）
    # --no-build-isolation 解决 setuptools.build_meta 找不到问题
    if pip install -e . --user --no-build-isolation; then
        ok "本地源码安装成功"
    else
        fail "pip install 失败"
        return 1
    fi
}

verify_pandaone_install() {
    step "5/6 验证 pandaone 可用"
    local check
    check=$(python -c "import pandaone; print('OK from:', pandaone.__file__); print('version:', pandaone.__version__)" 2>&1) || true
    if [[ "$check" == *"OK from:"* ]]; then
        echo -e "${C_OK}$check${C_RESET}"
        ok "pandaone 可导入"
        return 0
    else
        fail "pandaone 不可导入："
        echo "$check" >&2
        return 1
    fi
}

run_doctor() {
    step "6/6 运行 doctor.py 最终诊断"
    local doctor="$SCRIPT_DIR/doctor.py"
    if [[ ! -f "$doctor" ]]; then
        fail "未找到 $doctor"
        return 1
    fi
    python "$doctor"
}

# ============================================================
# 主流程
# ============================================================
banner

start_time=$(date +%s)

# Step 1: Python
python_cmd=$(find_python) || {
    echo ""
    fail "Python 检查失败，无法继续"
    exit 1
}

# Step 2: Git
if ! find_git; then
    echo ""
    warn "git 未找到，Pandaone 部分功能（rollback / pre-commit hook）会受限"
    info "可以继续，但建议先装 git"
    if ! confirm "        是否继续? (y/N) " "N"; then
        exit 1
    fi
fi

if [[ "$SKIP_INSTALL" -eq 0 ]]; then
    # Step 3: 卸载老版本
    uninstall_stale_pandaone

    # Step 4: 安装
    install_pandaone_editable || {
        echo ""
        fail "安装失败"
        exit 1
    }

    # Step 5: 验证
    verify_pandaone_install || {
        echo ""
        fail "验证失败"
        exit 1
    }
fi

if [[ "$SKIP_DOCTOR" -eq 0 ]]; then
    # Step 6: 最终诊断
    run_doctor
fi

end_time=$(date +%s)
duration=$((end_time - start_time))

echo ""
echo -e "${C_INFO}================================================================${C_RESET}"
echo -e "${C_INFO} 安装完成 — 耗时: ${duration}s${C_RESET}"
echo -e "${C_INFO}================================================================${C_RESET}"
echo ""
# ---- 注册 MCP server（可用 --skip-mcp 跳过）----
if [[ "$SKIP_MCP" -eq 0 ]]; then
    echo -e "${C_INFO}[MCP] 注册 MCP server 到 IDE 配置（Claude Desktop / Cursor / Trae）...${C_RESET}"
    if python -m pandaone install-mcp --client auto; then
        echo -e "${C_OK}  MCP 注册完成${C_RESET}"
    else
        echo -e "${C_WARN}MCP 注册失败，可手动执行: pandaone install-mcp${C_RESET}"
    fi
else
    echo -e "${C_WARN}[SKIP] MCP 注册 (per --skip-mcp)${C_RESET}"
fi

echo -e "${C_WARN}下一步：${C_RESET}"
echo "  pandaone install-mcp         # 注册 MCP server 到 IDE (Claude/Cursor/Trae)"
echo "  python -m pandaone --version         # 验证 CLI"
echo "  python scripts/doctor.py           # 详细诊断"
echo "  python -m pytest tests/ -q        # 跑全部测试"
echo ""
