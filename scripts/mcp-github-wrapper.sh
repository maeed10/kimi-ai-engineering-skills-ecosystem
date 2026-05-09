#!/usr/bin/env bash
# mcp-github-wrapper.sh — File-based secret injection for GitHub MCP server
# Kimi AI Engineering Skills Ecosystem v4.2.1
#
# Reads GITHUB_PERSONAL_ACCESS_TOKEN from a restricted file and injects it
# into the MCP server process environment. The token is NEVER stored in
# mcp.json (which may be readable by multiple processes).
#
# Secret file: ~/.kimi/secrets/github-token
# Permissions: chmod 600 ~/.kimi/secrets/github-token

set -euo pipefail

SECRET_FILE="${HOME}/.kimi/secrets/github-token"

if [[ ! -f "$SECRET_FILE" ]]; then
    echo "ERROR: GitHub token file not found at $SECRET_FILE" >&2
    echo "Create the file with your token and restrict permissions:" >&2
    echo "  mkdir -p ~/.kimi/secrets" >&2
    echo "  echo 'ghp_...' > ~/.kimi/secrets/github-token" >&2
    echo "  chmod 600 ~/.kimi/secrets/github-token" >&2
    exit 1
fi

GITHUB_TOKEN="$(cat "$SECRET_FILE")"
if [[ -z "$GITHUB_TOKEN" ]]; then
    echo "ERROR: GitHub token file is empty" >&2
    exit 1
fi

# Validate token format (basic prefix check)
if [[ ! "$GITHUB_TOKEN" =~ ^gh[pousr]_ ]]; then
    echo "WARNING: Token does not match expected GitHub PAT prefix (ghp_, gho_, ghu_, ghs_, or ghr_)" >&2
fi

# Launch the MCP server with the token in environment (process-local only)
export GITHUB_PERSONAL_ACCESS_TOKEN="$GITHUB_TOKEN"
exec npx -y @modelcontextprotocol/server-github
