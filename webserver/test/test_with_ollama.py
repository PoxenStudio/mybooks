import argparse
import requests
import json
import sys

def main():
    parser = argparse.ArgumentParser(description="Test Ollama with MCP")
    parser.add_argument("--ollama-host", default="127.0.0.1", help="Ollama Host IP")
    parser.add_argument("--mcp-url", required=True, help="MCP Service URL")
    args = parser.parse_args()

    ollama_url = f"http://{args.ollama_host}:11434/api/chat"
    mcp_url = args.mcp_url
    model = "qwen2.5:0.5b" # "qwen3:0.6b"
    mcp_name = "mybooks"

    print(f"Target MCP Service: {mcp_name} at {mcp_url}")
    print(f"Target Ollama: {ollama_url} with model {model}")

    # 1. Fetch tools from MCP
    print(f"\n[1] Fetching tools from MCP...")
    try:
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/list",
            "id": 1
        }
        response = requests.post(mcp_url, json=payload)
        response.raise_for_status()
        mcp_tools_response = response.json()

        if "error" in mcp_tools_response:
            print(f"MCP Error: {mcp_tools_response['error']}")
            sys.exit(1)

        mcp_tools = mcp_tools_response.get("result", {}).get("tools", [])
        print(f"Found {len(mcp_tools)} tools.")
        for t in mcp_tools:
            print(f" - {t['name']}: {t.get('description', 'No description')}")

    except Exception as e:
        print(f"Error fetching tools: {e}")
        sys.exit(1)

    # 2. Convert to Ollama tools format
    ollama_tools = []
    for tool in mcp_tools:
        ollama_tool = {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("inputSchema", {})
            }
        }
        ollama_tools.append(ollama_tool)

    # 3. Chat with Ollama
    messages = [
        {"role": "user", "content": "帮我查看一下 mybooks 里面有多少本书？"}
    ]

    print("\n[2] Sending request to Ollama...")
    payload = {
        "model": model,
        "messages": messages,
        "tools": ollama_tools,
        "stream": False
    }

    try:
        response = requests.post(ollama_url, json=payload)
        response.raise_for_status()
        chat_response = response.json()

        message = chat_response.get("message", {})
        print("Ollama response message:")
        print(json.dumps(message, ensure_ascii=False, indent=2))

        # 4. Handle Tool Calls
        if message.get("tool_calls"):
            print("\n[3] Tool calls detected. Executing...")
            messages.append(message) # Add assistant's message with tool calls

            for tool_call in message["tool_calls"]:
                function_name = tool_call["function"]["name"]
                arguments = tool_call["function"]["arguments"]

                print(f"Executing tool: {function_name}")
                print(f"Arguments: {arguments}")

                # Call MCP tool
                mcp_payload = {
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {
                        "name": function_name,
                        "arguments": arguments
                    },
                    "id": 2
                }
                mcp_response = requests.post(mcp_url, json=mcp_payload)
                mcp_result = mcp_response.json()

                tool_content = ""
                if "result" in mcp_result:
                    tool_content = json.dumps(mcp_result["result"], ensure_ascii=False)
                elif "error" in mcp_result:
                    tool_content = json.dumps(mcp_result["error"], ensure_ascii=False)
                else:
                    tool_content = "Unknown result"

                print(f"Tool result: {tool_content[:200]}..." if len(tool_content) > 200 else f"Tool result: {tool_content}")

                messages.append({
                    "role": "tool",
                    "content": tool_content,
                })

            # 5. Follow up with Ollama
            print("\n[4] Sending follow-up to Ollama with tool results...")
            payload["messages"] = messages

            response = requests.post(ollama_url, json=payload)
            response.raise_for_status()
            final_response = response.json()
            final_content = final_response.get("message", {}).get("content")
            print("\n[5] Final Answer:")
            print(final_content)
        else:
            print("\n[3] No tool calls made. Final answer:")
            print(message.get("content"))

    except Exception as e:
        print(f"Error communicating with Ollama: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
