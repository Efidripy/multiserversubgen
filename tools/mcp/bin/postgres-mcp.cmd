@echo off
setlocal
if "%DATABASE_URL%"=="" (
  echo DATABASE_URL is not set.>&2
  exit /b 1
)
call "%~dp0..\node_modules\.bin\mcp-server-postgres.cmd" "%DATABASE_URL%"
