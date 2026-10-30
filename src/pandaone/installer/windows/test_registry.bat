rem REMOVED - the sandbox registry key "Pandaone_test" is no longer produced by any
rem code path: install_context_menu.ps1 has no sandbox mode (only -DryRun, which
rem writes nothing) and the CLI installs the 3 real base keys only.  This script
rem could therefore never pass, it was truncated on creation (203 bytes / 5 lines,
rem ending at "call :check HKCU\...\Pandaone_test (Default) " parent) and is
rem superseded by test_registry.ps1 (real key) and test_registry_real.bat.
