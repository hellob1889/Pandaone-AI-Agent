@echo off
rem ================================================================
rem Pandaone right-click menu - registry structure assertion test
rem Pure cmd.exe (no PowerShell required).
rem
rem This file MUST stay pure ASCII (no Chinese, no UTF-8 BOM):
rem   - cmd.exe reads a .bat with the OEM code page (936/GBK on a
rem     Chinese Windows). A UTF-8 encoded Chinese character gets
rem     re-decoded as GBK and can swallow the byte that follows it
rem     (0x5C "\" is a legal GBK trail byte), which silently
rem     rewrites a registry path. ASCII is code page agnostic.
rem   - cmd.exe does NOT strip a UTF-8 BOM from a .bat. The first
rem     command becomes "<BOM>@echo", is not recognised, and the
rem     whole script then runs with echo switched on. (PowerShell 5.1
rem     behaves exactly the opposite way: there a BOM is mandatory.)
rem
rem Usage:
rem   1) Install the menu:
rem        powershell -ExecutionPolicy Bypass -File install_context_menu.ps1
rem        (or: pandaone install-context)
rem   2) Run this script. Every failed assertion prints a reason
rem      and the script exits with code 1.
rem
rem Asserted scope - the 3 real entry points (not a sandbox key):
rem   HKCU\Software\Classes\*\shell\Pandaone
rem   HKCU\Software\Classes\Directory\shell\Pandaone
rem   HKCU\Software\Classes\Directory\Background\shell\Pandaone
rem For each of them:
rem   - the parent key exists
rem   - the parent (Default) value is empty
rem   - ExtendedSubCommandsKey = Pandaone\Shell
rem   - Icon is present
rem   - Shell\ holds the 4 verbs Init / Lock / Status / Unlock
rem   - every verb has a command\ (Default) referencing pandaone.exe
rem ================================================================
setlocal EnableExtensions EnableDelayedExpansion

set "FAIL=0"
set "CLASSES=HKCU\Software\Classes"
set "VERBS=Init Lock Status Unlock"

echo === Pandaone right-click menu registry structure test ===
echo.

call :check_entry "*\shell"
call :check_entry "Directory\shell"
call :check_entry "Directory\Background\shell"

echo.
if "%FAIL%"=="0" (
    echo [OK]   all assertions passed
    endlocal
    exit /b 0
)
echo [FAIL] %FAIL% assertion(s) failed
endlocal
exit /b 1

:check_entry
set "BASE=%CLASSES%\%~1\Pandaone"
echo === %BASE% ===
call :assert_key "%BASE%" "parent key exists"
if "%EXISTS%"=="0" goto :eof
call :assert_default_empty "%BASE%"
call :assert_value_equals "%BASE%" "ExtendedSubCommandsKey" "Pandaone\Shell"
call :assert_value_present "%BASE%" "Icon"
for %%V in (%VERBS%) do call :assert_verb "%BASE%" "%%V"
goto :eof

:assert_verb
set "VKEY=%~1\Shell\%~2"
call :assert_key "%VKEY%" "verb %~2 exists"
if "%EXISTS%"=="0" goto :eof
call :assert_key "%VKEY%\command" "verb %~2 command key exists"
if "%EXISTS%"=="0" goto :eof
call :assert_default_contains "%VKEY%\command" "pandaone"
goto :eof

:assert_key
set "EXISTS=0"
reg query "%~1" >nul 2>&1
if not errorlevel 1 set "EXISTS=1"
if "%EXISTS%"=="1" (
    echo [OK]   %~2
) else (
    echo [FAIL] %~2 - %~1 not found
    set /a FAIL+=1
)
goto :eof

:assert_default_empty
rem "reg query <key> /ve" prints:
rem     <localized default name>    REG_SZ    <value>
rem The type token (REG_SZ) is never localized, the default value NAME
rem is - so the line is selected by its type, never by its name.
rem A value that is not set is printed as a parenthesised localized
rem placeholder, an empty value prints nothing at all. Both mean
rem "empty", which is what the PowerShell test asserts as well
rem (a null value becomes "" and IsNullOrEmpty is true).
set "DEFVAL="
for /f "tokens=3,*" %%A in ('reg query "%~1" /ve 2^>nul ^| findstr /c:"REG_SZ"') do set "DEFVAL=%%A%%B"
if not defined DEFVAL (
    echo [OK]   %~1 ^(Default^) is empty
    goto :eof
)
if "%DEFVAL:~0,1%"=="(" if "%DEFVAL:~-1%"==")" (
    echo [OK]   %~1 ^(Default^) is empty
    goto :eof
)
echo [FAIL] %~1 ^(Default^) must be empty, got "%DEFVAL%"
set /a FAIL+=1
goto :eof

:assert_default_contains
set "DEFVAL="
for /f "tokens=3,*" %%A in ('reg query "%~1" /ve 2^>nul ^| findstr /c:"REG_SZ"') do set "DEFVAL=%%A%%B"
if not defined DEFVAL (
    echo [FAIL] %~1 ^(Default^) is missing
    set /a FAIL+=1
    goto :eof
)
echo !DEFVAL! | findstr /i /c:"%~2" >nul
if errorlevel 1 (
    echo [FAIL] %~1 ^(Default^) does not reference %~2 - got "%DEFVAL%"
    set /a FAIL+=1
) else (
    echo [OK]   %~1 ^(Default^) references %~2
)
goto :eof

:assert_value_equals
set "GOT="
for /f "tokens=1,2,3,*" %%A in ('reg query "%~1" /v "%~2" 2^>nul') do (
    if /i "%%A"=="%~2" set "GOT=%%C%%D"
)
if "%GOT%"=="%~3" (
    echo [OK]   %~1 %~2 = %~3
) else (
    echo [FAIL] %~1 %~2 should be "%~3", got "%GOT%"
    set /a FAIL+=1
)
goto :eof

:assert_value_present
set "GOT="
for /f "tokens=1,2,3,*" %%A in ('reg query "%~1" /v "%~2" 2^>nul') do (
    if /i "%%A"=="%~2" set "GOT=%%C%%D"
)
if defined GOT (
    echo [OK]   %~1 %~2 is present
) else (
    echo [FAIL] %~1 %~2 is missing
    set /a FAIL+=1
)
goto :eof
