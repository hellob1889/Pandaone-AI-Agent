"""
test_ps1_powershell51_compat.py
================================
Windows PowerShell 5.1 compatibility gate for every tracked ``.ps1`` in this repo.

Why this gate exists
--------------------
Windows PowerShell 5.1 (the version shipped with Windows 10/11) reads a ``.ps1``
file **that has no UTF-8 BOM** using the system *ANSI* code page - cp936 / GBK on
a Chinese-locale machine.  A UTF-8 encoded Chinese script is therefore decoded as
GBK, which

* garbles every Chinese literal (the user sees mojibake), and
* can - and did - shift the byte alignment so badly that the **parser** reports
  syntax errors and the script refuses to run at all.

The scripts in ``docs/{zh,en}/context-menu.md`` are handed to the user verbatim::

    powershell -ExecutionPolicy Bypass -File installer\\windows\\install_context_menu.ps1

so this is a hard, user-facing failure - not a cosmetic one.

What is asserted
----------------
1. ``err51 == errU8`` for every tracked ``.ps1``:
   parsing the file the way 5.1 does *by default* must produce exactly as many
   errors as parsing its explicit UTF-8 decoding.  A difference means a
   "5.1-only" (encoding) failure.
2. ``errU8 == 0``:
   the file must be syntactically valid PowerShell.  Assertion 1 alone does NOT
   catch a real syntax error - a truncated script yields ``err51 == errU8 == 1``
   and would slip through assertion 1 unnoticed.
3. BOM policy:
   * scripts executed via ``powershell -File`` -> MUST carry a UTF-8 BOM when
     they contain non-ASCII characters, otherwise 5.1 mis-decodes them;
   * scripts consumed via ``irm <url> | iex``   -> MUST NOT carry a BOM, because
     ``Invoke-RestMethod`` keeps the BOM as a leading U+FEFF and ``iex`` then
     fails with ``CommandNotFoundException`` on the very first command.

Implementation notes (all of these were hit the hard way)
---------------------------------------------------------
* **Never** hand a Chinese path to ``powershell.exe``: 5.1 decodes the command
  line with the ANSI code page and fails with "path syntax is incorrect".
  Every file is therefore copied into a **pure ASCII** temporary directory first.
* The probe script itself must be pure ASCII (a Chinese probe cannot even be
  parsed by 5.1) and must receive the directory through an **environment
  variable**.  ``-Command "...$args[0]..."`` and ``-File probe.ps1 -Dir <path>``
  both mangle the argument.
* The probe output is plain ASCII; the Python side parses it.
* ``git ls-files -z`` must be split on **NUL**, never on newlines - a Chinese
  path would otherwise be truncated.
* Each file is probed twice: once byte-exact and once with CRLF normalised to
  LF.  GBK mis-decoding is alignment sensitive, so the number of 5.1 errors
  differs between the two forms; both must be free of 5.1-only errors.

The whole module is skipped on non-Windows platforms (no ``powershell.exe``),
so a Linux CI stays green.
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BOM = b"\xef\xbb\xbf"

pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason=(
        "Windows PowerShell 5.1 only exists on Windows; this gate needs the real "
        "powershell.exe to reproduce the ANSI/GBK reading behaviour."
    ),
)


# ---------------------------------------------------------------------------
# Scripts that the documentation tells users to consume with `irm <url> | iex`.
#
# A UTF-8 BOM is FATAL for that usage: Invoke-RestMethod returns the body with
# the BOM still attached as a leading U+FEFF, and `iex` then treats it as part
# of the first command name -> "CommandNotFoundException".  These scripts must
# therefore stay BOM-less.  Their Chinese still renders correctly because `irm`
# decodes the HTTP body as UTF-8 (charset=utf-8), not as ANSI.
# ---------------------------------------------------------------------------
IRM_IEX_SCRIPTS = frozenset({
    # docs/zh/install.md:18,86 ; docs/en/install.md:18,86 ;
    # .github/workflows/publish.yml:312
    "install.ps1",
    # scripts/install-update-latest.ps1 header + work/release_notes_v0_7_21_3.md:52
    "scripts/install-update-latest.ps1",
    # docs/zh/v0.7.20_user_install.md:14
    "scripts/install-update.ps1",
})


# ---------------------------------------------------------------------------
# Pure-ASCII probe.  It reports, for every .ps1 in $PD_PS1_DIR:
#   name | err51 | err51_lines | errU8 | errU8_lines | msg51 | msgU8
# err51 = number of errors when 5.1 reads the file with its *default* encoding
# errU8 = number of errors when the file is decoded as explicit UTF-8
# ---------------------------------------------------------------------------
PROBE_PS1 = r"""
$ErrorActionPreference = 'Stop'
$dir = $env:PD_PS1_DIR
$out = $env:PD_PS1_OUT
if (-not $dir -or -not $out) {
    Write-Error 'PD_PS1_DIR / PD_PS1_OUT env vars are required'
    exit 2
}
$lines = @()
foreach ($f in (Get-ChildItem -Path $dir -Filter '*.ps1' | Sort-Object Name)) {
    $t1 = $null
    $e51 = $null
    $null = [System.Management.Automation.Language.Parser]::ParseFile($f.FullName, [ref]$t1, [ref]$e51)
    $n51 = 0
    $l51 = ''
    $m51 = ''
    if ($e51) {
        $n51 = @($e51).Count
        $ls = @()
        foreach ($e in $e51) { $ls += [int]$e.Extent.StartLineNumber }
        $l51 = ($ls -join ',')
        $m51 = [string]$e51[0].Message
    }
    $txt = [System.IO.File]::ReadAllText($f.FullName, [System.Text.Encoding]::UTF8)
    $t2 = $null
    $eu8 = $null
    $null = [System.Management.Automation.Language.Parser]::ParseInput($txt, [ref]$t2, [ref]$eu8)
    $nu8 = 0
    $lu8 = ''
    $mu8 = ''
    if ($eu8) {
        $nu8 = @($eu8).Count
        $ls = @()
        foreach ($e in $eu8) { $ls += [int]$e.Extent.StartLineNumber }
        $lu8 = ($ls -join ',')
        $mu8 = [string]$eu8[0].Message
    }
    $m51 = ($m51 -replace '[^\x20-\x7E]', '?')
    $mu8 = ($mu8 -replace '[^\x20-\x7E]', '?')
    $lines += ($f.Name + '|' + $n51 + '|' + $l51 + '|' + $nu8 + '|' + $lu8 + '|' + $m51 + '|' + $mu8)
}
[System.IO.File]::WriteAllLines($out, $lines, (New-Object System.Text.UTF8Encoding($false)))
exit 0
"""


def _is_ascii(text):
    return all(ord(ch) < 128 for ch in text)


def _tracked_ps1():
    """Every tracked ``*.ps1``.

    ``git ls-files -z`` is split on NUL - never on newlines - because a path
    containing a Chinese character would be truncated by a line split.
    """
    try:
        raw = subprocess.check_output(
            ["git", "-C", str(ROOT), "ls-files", "-z"],
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    names = []
    for chunk in raw.split(b"\0"):
        if not chunk:
            continue
        try:
            name = chunk.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if name.lower().endswith(".ps1"):
            names.append(name)
    return names


def _ascii_tempdir():
    """A temporary directory whose path is pure ASCII.

    ``powershell.exe`` gets the probe path on its command line, and 5.1 decodes
    that with the ANSI code page - a Chinese path breaks it outright.
    """
    bases = [tempfile.gettempdir(), r"C:\Windows\Temp", r"C:\Temp", os.getcwd()]
    for base in bases:
        if not base or not _is_ascii(base):
            continue
        try:
            return Path(tempfile.mkdtemp(prefix="ps1compat_", dir=base))
        except OSError:
            continue
    pytest.skip("no pure-ASCII writable temporary directory available")


@pytest.fixture(scope="module")
def ps1_inventory():
    """``[(relative_path, raw_bytes), ...]`` for every tracked ``.ps1``."""
    inventory = []
    for rel in _tracked_ps1():
        path = ROOT / rel
        if not path.is_file():
            continue
        inventory.append((rel, path.read_bytes()))
    if not inventory:
        pytest.skip("no tracked .ps1 file found")
    return inventory


@pytest.fixture(scope="module")
def ps1_probe(ps1_inventory):
    """``{(rel_path, variant): {err51, errU8, lines51, linesU8, msg51, msgU8}}``.

    ``variant`` is ``"raw"`` (bytes exactly as stored) or ``"lf"`` (CRLF
    normalised to LF, i.e. the canonical form git stores thanks to
    ``*.ps1 text eol=lf``).
    """
    if shutil.which("powershell.exe") is None:
        pytest.skip("powershell.exe not found on PATH")

    tmp = _ascii_tempdir()
    try:
        files_dir = tmp / "files"
        files_dir.mkdir()
        probe = tmp / "probe.ps1"
        probe.write_bytes(PROBE_PS1.encode("ascii"))

        mapping = {}
        for index, (rel, raw) in enumerate(ps1_inventory):
            for variant, payload in (
                ("raw", raw),
                ("lf", raw.replace(b"\r\n", b"\n")),
            ):
                name = "%s_%03d.ps1" % (variant, index)
                (files_dir / name).write_bytes(payload)
                mapping[name] = (rel, variant)

        out_file = tmp / "probe_out.txt"
        env = dict(os.environ)
        env["PD_PS1_DIR"] = str(files_dir)
        env["PD_PS1_OUT"] = str(out_file)

        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", str(probe)],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
        assert proc.returncode == 0, (
            "probe failed (exit=%s)\nstdout=%s\nstderr=%s"
            % (proc.returncode, proc.stdout[:2000], proc.stderr[:2000])
        )
        assert out_file.exists(), "probe produced no output file"

        results = {}
        for line in out_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            fields = line.split("|", 6)
            assert len(fields) == 7, "unparsable probe line: %r" % line
            rel, variant = mapping[fields[0]]
            results[(rel, variant)] = {
                "err51": int(fields[1]),
                "lines51": fields[2],
                "errU8": int(fields[3]),
                "linesU8": fields[4],
                "msg51": fields[5],
                "msgU8": fields[6],
            }
        assert results, "probe returned no results"
        return results
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)


def test_every_tracked_ps1_parses_identically_under_powershell_51_and_utf8(ps1_probe):
    """err51 must equal errU8 - no "5.1-only" (encoding) failures.

    This is the assertion that catches the encoding class of bug: 5.1 reads a
    BOM-less UTF-8 file as ANSI/GBK, and the resulting mojibake can break the
    parser outright.
    """
    offenders = []
    for (rel, variant), info in sorted(ps1_probe.items()):
        if info["err51"] != info["errU8"]:
            offenders.append(
                "%s [%s]: err51=%d errU8=%d (lines51=%s) msg51=%s"
                % (rel, variant, info["err51"], info["errU8"],
                   info["lines51"], info["msg51"])
            )
    assert not offenders, (
        "Windows PowerShell 5.1 reads these .ps1 files differently from UTF-8 "
        "(missing UTF-8 BOM => ANSI/GBK mis-decoding):\n  " + "\n  ".join(offenders)
    )


def test_every_tracked_ps1_is_syntactically_valid(ps1_probe):
    """errU8 must be 0 - no real syntax error in any tracked .ps1.

    Kept separate from the assertion above on purpose: a *truncated* script
    produces ``err51 == errU8 == 1`` and would pass an equality check.
    """
    offenders = []
    for (rel, variant), info in sorted(ps1_probe.items()):
        if info["errU8"] != 0:
            offenders.append(
                "%s [%s]: %d parse error(s) at line(s) %s - %s"
                % (rel, variant, info["errU8"], info["linesU8"], info["msgU8"])
            )
    assert not offenders, (
        "these .ps1 files are not valid PowerShell:\n  " + "\n  ".join(offenders)
    )


def test_ps1_bom_policy(ps1_inventory):
    """BOM presence must follow the way the script is consumed.

    * ``powershell -File``  -> BOM required as soon as the file has non-ASCII,
      otherwise 5.1 mis-decodes it (garbled UI and possibly a syntax error).
    * ``irm <url> | iex``   -> BOM forbidden, it would break ``iex``.
    """
    problems = []
    for rel, raw in ps1_inventory:
        has_bom = raw.startswith(BOM)
        body = raw[3:] if has_bom else raw
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            problems.append("%s: not valid UTF-8" % rel)
            continue
        has_non_ascii = any(ord(ch) > 127 for ch in text)
        if rel in IRM_IEX_SCRIPTS:
            if has_bom:
                problems.append(
                    "%s is consumed with `irm | iex`; a UTF-8 BOM breaks iex "
                    "(CommandNotFoundException) - remove the BOM" % rel
                )
        elif has_non_ascii and not has_bom:
            problems.append(
                "%s contains non-ASCII characters but has no UTF-8 BOM; "
                "Windows PowerShell 5.1 would read it as ANSI/GBK" % rel
            )
    assert not problems, "BOM policy violations:\n  " + "\n  ".join(problems)


def test_irm_iex_script_list_is_still_accurate(ps1_inventory):
    """The ``irm | iex`` allow-list must not rot silently."""
    tracked = {rel for rel, _ in ps1_inventory}
    missing = IRM_IEX_SCRIPTS - tracked
    assert not missing, (
        "these files are listed as `irm | iex` scripts but no longer exist: %s"
        % sorted(missing)
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
