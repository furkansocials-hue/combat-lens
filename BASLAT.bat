@echo off
rem Combat Lens - kaynak koddan acar (konsol penceresi olmadan).
rem Proje klasorundeki .venv varsa onu kullanir (yeni arayuz pywebview ister);
rem yoksa sistemdeki Python ile acar, pywebview yoksa klasik pencere gelir.
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" -m aion2meter %*
) else (
  start "" pythonw -m aion2meter %*
)
