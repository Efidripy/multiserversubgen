@echo off
setlocal
if "%ALLOWED_CONTAINERS%"=="" set "ALLOWED_CONTAINERS=app:app_container"
if "%DEFAULT_SERVICE%"=="" set "DEFAULT_SERVICE=app"
if "%COMMAND_TIMEOUT%"=="" set "COMMAND_TIMEOUT=300000"
call "%~dp0..\node_modules\.bin\mcp-server-docker.cmd"
