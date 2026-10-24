@echo off
rem Double-click: (1) retry repos of the 5,000-repo sample that failed,
rem (2) scan the 453 supplementary repos from the destructiveHint-only search.
rem Safe to close and rerun: finished repos are skipped.
cd /d "%~dp0"
title MCP scan (retry + supplement) - do not close
echo Step 1/2: retrying failed repos of the main sample
.venv\Scripts\python.exe scripts\scan_repos.py --target 5000 --workers 6
echo.
echo Step 2/2: supplementary repos (destructiveHint without readOnlyHint)
.venv\Scripts\python.exe scripts\scan_repos.py --dataset data\processed\dataset_repos_supplement.csv --workers 6
echo.
echo Done. If a step stopped early, double-click run_scan_extra.cmd again to resume.
pause
