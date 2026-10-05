@echo off
"%~dp0Bww.Server.exe" --sync %*
set "bwwSyncExit=%errorlevel%"
pause
exit /b %bwwSyncExit%
