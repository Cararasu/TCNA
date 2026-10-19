@echo off
rem Start the CNA server (tools/review/server.py) and open the game's title screen in the browser.
rem The map editor is at http://127.0.0.1:PORT/editor.html (see start-editor.cmd).
rem Usage: start-game.cmd [port]     (default port 8765; Ctrl+C to stop)
setlocal
cd /d "%~dp0"

set "PORT=%~1"
if "%PORT%"=="" set "PORT=8765"

where python >nul 2>nul || (
    echo Python was not found on PATH.
    goto :fail
)
python -c "import PIL" 2>nul || (
    echo Pillow is not installed. Install it with:  python -m pip install Pillow
    goto :fail
)

rem Open the browser once the server has had a moment to start listening.
start "" /b cmd /c "timeout /t 2 /nobreak >nul & start http://127.0.0.1:%PORT%/"

python tools\review\server.py --port %PORT%
exit /b %errorlevel%

:fail
pause
exit /b 1
