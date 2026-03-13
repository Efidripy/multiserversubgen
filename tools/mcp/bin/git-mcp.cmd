@echo off
setlocal
if "%GIT_DEFAULT_PATH%"=="" set "GIT_DEFAULT_PATH=E:\GitHub\multiserversubgen"
call "%~dp0..\node_modules\.bin\git-mcp-server.cmd"
