@echo off
rem Meter'i acar ve oyun akisini %APPDATA%\CombatLens\kayitlar\ klasorune kaydeder.
rem Bir savasta rakamlar sana yanlis gelirse bununla calistir; kaydi sonra
rem "python -m aion2meter --replay DOSYA.txt" ile tekrar acabilirsin.
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" -m aion2meter --record %*
) else (
  start "" pythonw -m aion2meter --record %*
)
