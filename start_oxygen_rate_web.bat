@echo off
cd /d "%~dp0"
start "" "http://127.0.0.1:8765"
"C:\Users\19104\AppData\Local\Programs\Python\Python311\python.exe" oxygen_rate_web.py --port 8765
pause
