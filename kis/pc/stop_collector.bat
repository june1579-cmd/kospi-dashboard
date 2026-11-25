@echo off
cd /d "%~dp0"
if not exist state mkdir state
echo stop> state\STOP
schtasks /Delete /TN "KIS_Minute_Collector" /F >nul 2>nul
echo Stop requested. The collector will finish its current step and exit within about 1 minute.
echo Data already collected is kept. To resume later, run start_collector.bat again.
pause
