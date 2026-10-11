#!/usr/bin/env sh
# Build the fixed MCP launcher (Linux CI or any host with mingw-w64). Output: $1 (default workspace/mcp/mxstudio-mcp.exe)
set -eu
here=$(cd "$(dirname "$0")" && pwd)
out=${1:-workspace/mcp/mxstudio-mcp.exe}
mkdir -p "$(dirname "$out")"
x86_64-w64-mingw32-gcc -O2 -s -municode -mwindows -Wall -Wextra -Werror -o "$out" "$here/mxstudio_mcp.c" -ladvapi32
echo "built $out ($(wc -c < "$out") bytes)"
