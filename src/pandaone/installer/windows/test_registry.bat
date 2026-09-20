@echo off
rem Test plan 2 registry structure - pure cmd.exe, no Chinese
setlocal enabledelayedexpansion
set FAIL=0

call :check HKCU\Software\Classes\Directory\shell\Pandaone_test (Default) " parent