#!/bin/bash
# Server: talebook-mcp v0.1.0
set -euo pipefail

TOOL_NAME="${1:?Usage: talebook-mcp.sh <tool-name> '<json-args>'}"
ARGS="${2:-}"
[ -z "$ARGS" ] && ARGS='{}'
MCP_URL="http://192.168.31.102:8082/api/mcp/stream?token=<token>"

# Capture session ID from initialize (required for stateful servers; no-op for stateless)
TEMP_HEADERS=$(mktemp)
curl -s -X POST "$MCP_URL" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -D "$TEMP_HEADERS" \
  -d '{"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"mcptoskill","version":"0.1.0"}}}' > /dev/null

SESSION_ID=$(grep -i "^mcp-session-id:" "$TEMP_HEADERS" | awk '{print $2}' | tr -d '\r' || true)
rm -f "$TEMP_HEADERS"

# Call the tool
if [ -n "$SESSION_ID" ]; then
  RESPONSE=$(curl -s -X POST "$MCP_URL" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" \
    -H "Mcp-Session-Id: $SESSION_ID" \
    -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/call\",\"params\":{\"name\":\"$TOOL_NAME\",\"arguments\":$ARGS}}")
else
  RESPONSE=$(curl -s -X POST "$MCP_URL" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" \
    -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/call\",\"params\":{\"name\":\"$TOOL_NAME\",\"arguments\":$ARGS}}")
fi

# Handle SSE format (event: message / data: {...}) or plain JSON
if echo "$RESPONSE" | grep -q '^data: '; then
  echo "$RESPONSE" | grep '^data: ' | tail -1 | sed 's/^data: //'
else
  echo "$RESPONSE"
fi