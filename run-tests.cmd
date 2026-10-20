@echo off
rem Run the tests (python -m unittest) from the project folder.
rem Usage: run-tests.cmd [test ...]     e.g.  run-tests.cmd tests.test_engine
rem        run-tests.cmd -v             to list each test as it runs
rem With no arguments every test runs. The parity tests also need Node.js on PATH.
setlocal
cd /d "%~dp0"

where python >nul 2>nul || (
    echo Python was not found on PATH.
    set "RESULT=1"
    goto :end
)

python -m unittest %*
set "RESULT=%errorlevel%"

:end
rem Keep the window open when started by double-click: only then does cmd's
rem command line end in a space (Explorer runs: cmd.exe /c ""script.cmd" ").
set "CMDLINE=%cmdcmdline:"=%"
if "%CMDLINE:~-1%"==" " pause
exit /b %RESULT%
