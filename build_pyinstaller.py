#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_pyinstaller.py — Pandaone AI Agent Windows release packager.

Replaces the legacy single-file packager (it still pointed at the removed
``pandaone.py`` / ``pandaone_guard.py`` / ``install_hook.py`` at repo root and
at a non-existent ``installer/pandaone.iss``).  The project is now a src-layout
package tree, so every path below is derived from ``src/``.

Pipeline
--------
  0. preflight   — check PyInstaller / source layout / version
  1. clean       — remove stale build/, dist/, installer/staging, installer/Output
  2. build       — PyInstaller x3: pandaone.exe / pandaone_guard.exe / pandaone-mcp.exe
  3. merge       — fold the two satellite _internal dirs into pandaone's
  4. staging     — flatten dist/pandaone into installer/staging
  5. iss         — render src/pandaone/installer/codeaudit.iss with the live
                   version + icon + output name
  6. inno        — compile with ISCC.exe -> installer/Output/PandaoneSetup-<ver>-x64.exe

Why the package source tree is copied in as *data*
--------------------------------------------------
``src/pandaone/cli.py`` loads its subcommands by ``exec()``-ing the files in
``cli_chunks/`` at runtime, and the L5 self-fingerprint hashes the whole package
directory.  Neither survives a plain PyInstaller build: the .py files would be
compiled into the PYZ archive and vanish from disk.

So we copy the whole ``src/pandaone`` and ``src/pandaone_guard`` trees into the
bundle as data.  That keeps (a) the exec-based CLI loader working and (b) the
fingerprint scope identical between a source checkout and a frozen .exe.

Usage
-----
    python build_pyinstaller.py              # full build
    python build_pyinstaller.py --skip-iss   # only produce dist/pandaone/
    python build_pyinstaller.py --clean-only
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
PKG = SRC / "pandaone"
GUARD = SRC / "pandaone_guard"
MCP = SRC / "pandaone_mcp"
PACKAGING = ROOT / "packaging"

#: 上一次成功打包的版本记录。
#:
#: 为什么需要它：frozen 形态的指纹记录了 {version, hash, form}。exe 字节一变
#: hash 就变，而版本号没变时会被判定为「篡改」→ 整个 CLI 锁死（连 --version
#: 都打不开）。也就是说**同版本号重新打包 = 存量用户集体变砖**。发布必须抬
#: 版本号，这里把这条规则做成构建门禁而不是靠记性。
RELEASE_STATE = ROOT / ".pandaone" / "release_state.json"

DIST = ROOT / "dist"
STAGING = ROOT / "installer" / "staging"
ISSUED = ROOT / "installer" / "Output"
ISS_TEMPLATE = PKG / "installer" / "codeaudit.iss"
ISS_RENDERED = ROOT / "installer" / "pandaone.iss"

ISCC_CANDIDATES = [
    Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
    Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
    Path(r"C:\Program Files (x86)\Inno Setup 5\ISCC.exe"),
    # per-user install (winget / Inno Setup default for the current user)
    Path.home() / "AppData" / "Local" / "Programs" / "Inno Setup 6" / "ISCC.exe",
]

#: Third-party + package modules that PyInstaller's static analysis cannot see.
#: The cli_chunks/*.py are exec()'d at runtime, so their imports are invisible
#: to the module graph — every one of them must be declared explicitly.
HIDDEN_IMPORTS = [
    # chunk 内 exec 出来的 import（静态分析抓不到）
    "pandaone.exporters",
    "pandaone.i18n",
    "pandaone.fp_security",
    "pandaone.gitignore_helper",
    "pandaone.desktop_icon",
    "pandaone.git_installer",
    "pandaone.pandaone_serve",
    "pandaone.i18n_extras",
    "pandaone.git_ops",
    # monkey-patch 注册的新子命令
    "pandaone.cmd_doctor",
    "pandaone.cmd_setup",
    "pandaone.cmd_upgrade",
    "pandaone.cmd_backup",
    "pandaone.cmd_install_mcp",
    "pandaone_guard",
    # 第三方
    "psutil",
    "yaml",
    "watchdog",
    "watchdog.events",
    "watchdog.observers",
    "watchdog.observers.polling",
    "pkg_resources",
]
if os.name == "nt":
    HIDDEN_IMPORTS.append("winreg")  # part_006 里 exec 出来的 Windows 注册表操作


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def run(cmd: list[str], cwd: Path | None = None) -> int:
    print(f"$ {' '.join(str(c) for c in cmd)}")
    r = subprocess.run([str(c) for c in cmd], cwd=str(cwd) if cwd else None)
    return r.returncode


def read_version() -> str:
    """Read the single source of truth for the version: pyproject.toml."""
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^\s*version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not m:
        raise SystemExit("version not found in pyproject.toml")
    return m.group(1)


def data_sep() -> str:
    return ";" if os.name == "nt" else ":"


def add_data(src: Path, dest: str) -> str:
    """Build one --add-data argument (dest must be a directory)."""
    return f"{src}{data_sep()}{dest}"


def package_data_args() -> list[str]:
    """--add-data arguments.

    The whole package tree is copied verbatim so that
      * cli_chunks/part_*.py stay readable by the exec() based CLI loader, and
      * the L5 fingerprint scope matches the source checkout exactly.

    ``_build_info.py`` (version stamp) is injected into the pandaone/ folder
    of the bundle — a frozen exe has no pyproject.toml to read the version
    from.
    """
    args = [
        add_data(PKG, "pandaone"),
        add_data(GUARD, "pandaone_guard"),
    ]
    stamp = ROOT / "build" / "_build_info.py"
    if stamp.is_file():
        args.append(add_data(stamp, "pandaone"))
    return args


def pyinstaller_cmd(name: str, entry: Path, extra_data: list[str] | None = None) -> list[str]:
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", name,
        "--onedir",
        "--console",
        "--noconfirm",
        "--clean",
        "--paths", str(SRC),
        "--distpath", str(DIST),
        "--workpath", str(ROOT / "build" / name),
        "--specpath", str(ROOT / "build"),
    ]
    for d in (extra_data or []) + package_data_args():
        cmd += ["--add-data", d]
    for mod in HIDDEN_IMPORTS:
        cmd += ["--hidden-import", mod]
    for mod in ("tkinter", "matplotlib", "numpy", "PIL"):
        cmd += ["--exclude-module", mod]
    cmd.append(str(entry))
    return cmd


# ---------------------------------------------------------------------------
# steps
# ---------------------------------------------------------------------------

def preflight() -> str:
    print("\n[0/6] Preflight...")
    missing = [p for p in (PKG, GUARD, MCP, PACKAGING) if not p.is_dir()]
    if missing:
        raise SystemExit(f"missing source layout: {[str(p) for p in missing]}")
    r = subprocess.run([sys.executable, "-m", "PyInstaller", "--version"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit("PyInstaller not installed.  pip install pyinstaller")
    print(f"  PyInstaller {r.stdout.strip()}")
    version = read_version()
    print(f"  version {version}")
    return version


def read_release_state() -> dict:
    try:
        return json.loads(RELEASE_STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_release_state(version: str) -> None:
    """记录本次成功打包的版本 + exe 摘要（供下一次构建做版本守卫）。"""
    digest = ""
    exe = DIST / "pandaone" / "pandaone.exe"
    if exe.is_file():
        digest = hashlib.sha256(exe.read_bytes()).hexdigest()
    try:
        RELEASE_STATE.parent.mkdir(parents=True, exist_ok=True)
        RELEASE_STATE.write_text(
            json.dumps(
                {
                    "version": version,
                    "pandaone_exe_sha256": digest,
                    "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"  wrote {RELEASE_STATE.relative_to(ROOT)} (version {version})")
    except Exception as e:
        print(f"  [WARN] 未能写入 release state: {e}")


def check_version_bump(version: str, allow_same: bool) -> None:
    """拒绝同版本号重打包（除非显式 --allow-same-version）。"""
    state = read_release_state()
    last = str(state.get("version") or "")
    if not last or last != version:
        return
    print(f"[WARN] The previous successful build was also version {version}.")
    print("[WARN] Rebuilding the same version changes the exe bytes -> the")
    print("[WARN] fingerprint hash changes -> existing users get flagged as")
    print("[WARN] TAMPERED and their whole CLI locks up.")
    if allow_same:
        print("[WARN] --allow-same-version given; continuing (local verification only, do not release)")
        return
    raise SystemExit(
        f"[ERROR] Refusing to rebuild the same version ({version}). "
        f"Bump the version in pyproject.toml first; "
        f"use --allow-same-version for local verification only."
    )


def clean() -> None:
    print("\n[1/6] Clean stale artifacts...")
    for d in (ROOT / "build", DIST, STAGING, ISSUED):
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
            print(f"  removed {d.relative_to(ROOT)}")
    # __pycache__ inside the package tree would be copied into the bundle
    for cache in list(SRC.rglob("__pycache__")):
        shutil.rmtree(cache, ignore_errors=True)
    # generated build stamp (recreated below)
    bi = PKG / "_build_info.py"
    if bi.exists():
        bi.unlink()
    print("  purged __pycache__ under src/")


def write_build_info(version: str) -> Path:
    """Generate the version stamp that travels with the bundle.

    A frozen .exe has neither pyproject.toml nor install metadata, so the
    version has to travel with the bundle.  ``pandaone/__init__.py`` reads
    ``_MEIPASS/pandaone/_build_info.py`` when running frozen.

    The file is written to the (git-ignored) build/ directory, NOT into the
    source tree — the source tree must stay clean, otherwise the source-tree
    fingerprint would change on every build.
    """
    from datetime import datetime, timezone

    bi = ROOT / "build" / "_build_info.py"
    bi.parent.mkdir(parents=True, exist_ok=True)
    bi.write_text(
        "# -*- coding: utf-8 -*-\n"
        "# Generated by build_pyinstaller.py - DO NOT EDIT.\n"
        f'__version__ = "{version}"\n'
        f'BUILD_TIMESTAMP = "{datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}"\n',
        encoding="utf-8",
    )
    print(f"  wrote {bi.relative_to(ROOT)} (version {version})")
    return bi


def build_all() -> int:
    print("\n[2/6] PyInstaller build...")
    jobs = [
        ("pandaone", PACKAGING / "entry_pandaone.py"),
        ("pandaone_guard", PACKAGING / "entry_guard.py"),
        ("pandaone-mcp", PACKAGING / "entry_mcp.py"),
    ]
    for name, entry in jobs:
        print(f"  -> {name}.exe")
        rc = run(pyinstaller_cmd(name, entry))
        if rc != 0:
            print(f"  [FAIL] {name}")
            return rc
    return 0


def merge_internals() -> None:
    print("\n[3/6] Merge satellite _internal dirs...")
    target = DIST / "pandaone" / "_internal"
    for satellite in ("pandaone_guard", "pandaone-mcp"):
        src = DIST / satellite / "_internal"
        if src.exists() and target.exists():
            for item in src.iterdir():
                dst = target / item.name
                if item.is_dir():
                    if dst.exists():
                        shutil.rmtree(dst, ignore_errors=True)
                    shutil.copytree(item, dst)
                else:
                    shutil.copy2(item, dst)
            print(f"  merged {satellite}/_internal")
        exe = DIST / satellite / f"{satellite}.exe"
        if exe.exists():
            shutil.copy2(exe, DIST / "pandaone" / exe.name)
            print(f"  copied {exe.name}")


def prepare_staging() -> None:
    print("\n[4/6] Prepare staging...")
    STAGING.mkdir(parents=True, exist_ok=True)
    src = DIST / "pandaone"
    for item in src.iterdir():
        dst = STAGING / item.name
        if item.is_dir():
            if dst.exists():
                shutil.rmtree(dst, ignore_errors=True)
            shutil.copytree(item, dst)
        else:
            shutil.copy2(item, dst)
    print(f"  staged {len(list(src.iterdir()))} entries -> {STAGING.relative_to(ROOT)}")


def render_iss(version: str, iscc: Path | None = None) -> Path:
    """Render the Inno Setup script with the live version / icon / output name."""
    print("\n[5/6] Render Inno Setup script...")
    text = ISS_TEMPLATE.read_text(encoding="utf-8")

    text = re.sub(r'#define MyAppVersion "[^"]*"',
                  f'#define MyAppVersion "{version}"', text)
    text = re.sub(r'OutputBaseFilename=.*',
                  lambda _m: 'OutputBaseFilename=PandaoneSetup-{#MyAppVersion}-x64', text)
    # assets/pandaone.ico never existed; the shipped icons live in assets/
    # NOTE: replacement must be a lambda — a plain string would interpret the
    # backslashes of "..\assets\..." as regex escapes.
    text = re.sub(r'SetupIconFile=.*',
                  lambda _m: r'SetupIconFile=..\assets\pandax_unlocked.ico', text)

    # Inno Setup ships English + ~30 translations, but NOT Simplified Chinese
    # (that .isl is a third-party add-on).  Only keep the language entry when
    # the file is actually present, otherwise ISCC aborts the whole compile.
    if iscc is not None:
        lang_dir = iscc.parent / "Languages"
        if not (lang_dir / "ChineseSimplified.isl").exists():
            text = re.sub(r'^Name:\s*"chinesesimp".*\n', "", text, flags=re.M)
            print("  Simplified Chinese .isl not installed -> english only")

    ISS_RENDERED.parent.mkdir(parents=True, exist_ok=True)
    ISS_RENDERED.write_text(text, encoding="utf-8")
    print(f"  wrote {ISS_RENDERED.relative_to(ROOT)} (version {version})")
    return ISS_RENDERED


def find_iscc() -> Path | None:
    which = shutil.which("iscc")
    if which:
        return Path(which)
    for p in ISCC_CANDIDATES:
        if p.exists():
            return p
    return None


def try_inno_setup(version: str) -> int:
    print("\n[6/6] Inno Setup compile...")
    iscc = find_iscc()
    iss = render_iss(version, iscc)
    if iscc is None:
        print("  [SKIP] Inno Setup 6 not found.")
        print("         install: winget install JRSoftware.InnoSetup")
        print(f"         or run : \"{iscc}\" {iss}" if iscc else
              "         then  : iscc installer\\pandaone.iss")
        return 0
    rc = run([str(iscc), str(iss)])
    if rc == 0 and ISSUED.exists():
        exes = sorted(ISSUED.glob("*.exe"))
        for exe in exes:
            print(f"  [OK] {exe.name}  ({exe.stat().st_size:,} bytes)")
    else:
        print(f"  [FAIL] ISCC rc={rc}")
    return rc


def main() -> int:
    ap = argparse.ArgumentParser(description="Pandaone Windows release packager")
    ap.add_argument("--skip-iss", action="store_true", help="only build dist/pandaone/")
    ap.add_argument("--iss-only", action="store_true",
                    help="re-render and recompile the installer only (reuse dist/)")
    ap.add_argument("--clean-only", action="store_true", help="clean and exit")
    ap.add_argument(
        "--allow-same-version",
        action="store_true",
        help="允许同版本号重打包（仅本地验证用；发布会锁死存量用户的 CLI）",
    )
    args = ap.parse_args()

    print("=" * 64)
    print("Pandaone AI Agent — release packager")
    print("=" * 64)

    version = preflight()
    if args.iss_only:
        # 只重打安装包，exe 字节没变 → 不受同版本守卫限制
        try_inno_setup(version)
        return 0

    check_version_bump(version, args.allow_same_version)

    clean()
    if args.clean_only:
        return 0
    write_build_info(version)

    if build_all() != 0:
        print("\n[ERROR] PyInstaller build failed")
        return 1
    merge_internals()
    prepare_staging()

    if not args.skip_iss:
        try_inno_setup(version)

    print("\n" + "=" * 64)
    print("[OK] Pack finished")
    print("=" * 64)
    dist = DIST / "pandaone"
    if dist.exists():
        for exe in sorted(dist.glob("*.exe")):
            print(f"  dist/pandaone/{exe.name}  ({exe.stat().st_size:,} bytes)")
    if ISSUED.exists():
        for exe in sorted(ISSUED.glob("*.exe")):
            print(f"  installer/Output/{exe.name}  ({exe.stat().st_size:,} bytes)")
    write_release_state(version)
    return 0


if __name__ == "__main__":
    sys.exit(main())
