@echo off
cd /d "%~dp0"
py -3 bww_sd_copy.py
if errorlevel 1 (
  echo.
  echo Install Python 3.10 or newer if the py command is not found.
  echo See BWW_SD_COPY_README.md for instructions.
  pause
)
