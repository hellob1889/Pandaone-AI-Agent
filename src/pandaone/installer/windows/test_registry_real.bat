@echo off
rem Test real Pandaone registry entries (not sandbox)
setlocal enabledelayedexpansion
set FAIL=0
set TARGET=\shell\Pandaone

rem Entry 1: 任意文件
call :assert_parent *%TARGET% Entry