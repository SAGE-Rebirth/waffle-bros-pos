@echo off
REM Double-click to start the Waffle Bros POS on Windows.
cd /d "%~dp0"

where uv >nul 2>nul
if errorlevel 1 (
  echo uv is not installed. Open PowerShell and run:
  echo.
  echo   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  echo.
  echo Then close this window and double-click start-pos.bat again.
  goto :error
)

echo Checking Python packages...
uv sync || goto :error

if exist frontend\dist\index.html goto :run
where npm >nul 2>nul
if errorlevel 1 (
  echo WARNING: the screens are not built and Node.js is not installed.
  echo Install Node.js 22 or newer from https://nodejs.org to build them.
  goto :run
)
echo First run: building the screens, this takes a minute...
pushd frontend
call npm ci || (popd & goto :error)
call npm run build || (popd & goto :error)
popd

:run

start "" http://localhost:4000
uv run waffle-pos
goto :eof

:error
echo.
echo Could not start the POS. See the message above.
pause
exit /b 1
