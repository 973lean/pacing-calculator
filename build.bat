@echo off
rem Local Windows build. Requires: pip install pyinstaller
pyinstaller --onefile --windowed --noconfirm --name PacingCalculator --icon PacingCalculator.ico --add-data "PacingCalculator.ico;." app.py
echo.
echo Built: dist\PacingCalculator.exe
