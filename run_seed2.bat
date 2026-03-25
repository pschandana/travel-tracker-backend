@echo off
venv\Scripts\python.exe seed2.py > seed2_output.txt 2>&1
echo Exit: %ERRORLEVEL% >> seed2_output.txt
