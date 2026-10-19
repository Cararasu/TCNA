@echo off
rem Start the CNA server (python -m cna.server) and open the map editor in the browser.
rem The game itself is at http://127.0.0.1:PORT/ (see start-game.cmd).
rem Usage: start-editor.cmd [port]     (default port 8765; Ctrl+C to stop)
setlocal
cd /d "%~dp0"

set "PORT=%~1"
if "%PORT%"=="" set "PORT=8765"

where python >nul 2>nul || (
    echo Python was not found on PATH.
    goto :fail
)
python -c "import PIL, numpy" 2>nul || (
    echo Pillow or NumPy is missing. Install them with:  python -m pip install -r requirements.txt
    goto :fail
)

rem Open the browser once the server has had a moment to start listening.
start "" /b cmd /c "timeout /t 2 /nobreak >nul & start http://127.0.0.1:%PORT%/editor.html"

python -m cna.server --port %PORT%
exit /b %errorlevel%

:fail
pause
exit /b 1
