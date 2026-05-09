@echo off
REM mcp-github-wrapper.cmd — File-based secret injection for GitHub MCP server
REM Kimi AI Engineering Skills Ecosystem v4.2.1
REM
REM Reads GITHUB_PERSONAL_ACCESS_TOKEN from a restricted file and injects it
REM into the MCP server process environment. The token is NEVER stored in
REM mcp.json (which may be readable by multiple processes).
REM
REM Secret file: %USERPROFILE%\.kimi\secrets\github-token
REM Permissions: Owner read-only (0o600 equivalent on Windows)

setlocal enabledelayedexpansion

set "SECRET_FILE=%USERPROFILE%\.kimi\secrets\github-token"

if not exist "%SECRET_FILE%" (
    echo ERROR: GitHub token file not found at %SECRET_FILE% >&2
    echo Create the file with your token and restrict permissions: >&2
    echo   icacls "%SECRET_FILE%" /inheritance:r /grant:r "%%USERNAME%%:(RX)" >&2
    exit /b 1
)

set /p GITHUB_TOKEN=<"%SECRET_FILE%"

if "!GITHUB_TOKEN!"=="" (
    echo ERROR: GitHub token file is empty >&2
    exit /b 1
)

REM Launch the MCP server with the token in environment (process-local only)
set "GITHUB_PERSONAL_ACCESS_TOKEN=!GITHUB_TOKEN!"
npx -y @modelcontextprotocol/server-github
