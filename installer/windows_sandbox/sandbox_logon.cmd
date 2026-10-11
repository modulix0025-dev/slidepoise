@echo off
rem ModuleX Magazine Studio - Windows Sandbox logon command (ASCII-only).
rem Starts the proof hidden; results land in Desktop\mxs-results (mapped to the host).
start "MXS sandbox proof" /min powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "%USERPROFILE%\Desktop\mxs\sandbox_proof.ps1"
