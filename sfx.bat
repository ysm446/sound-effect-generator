@echo off
rem Command-line entry point: sfx generate "door creak" --seconds 4
rem Starts the Python backend in the background if it is not already running.
"%~dp0.venv\Scripts\python.exe" "%~dp0backend\cli.py" %*
