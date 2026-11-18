@echo off
REM Double-click to start the Waffle Bros POS on Windows.
cd /d "%~dp0"
if not exist node_modules (
  echo First run: installing and building, this takes a minute...
  call npm run setup || goto :error
)
if not exist client\dist call npm run build
start "" http://localhost:4000
call npm start
goto :eof
:error
echo Setup failed. Make sure Node.js 22 or newer is installed from https://nodejs.org
pause
