@echo off
rem Double-click to run (or resume) the repository scan in its own window.
rem It scans until 5,000 repos are in data\results\scan_manifest.csv, then stops.
rem Safe to close and rerun at any time: finished repos are skipped.
cd /d "%~dp0"
title MCP scan - do not close
echo Scanning MCP repos. Keep this window open and the laptop plugged in.
echo Progress is printed every 25 repos. You can close Claude; not this window.
echo.
.venv\Scripts\python.exe scripts\scan_repos.py --target 5000 --workers 6
echo.
echo Scan stopped. If it did not reach 5000, double-click run_scan.cmd again to resume.
pause
