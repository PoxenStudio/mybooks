"""
   python ./test_vllm_with_mcp.py --mcp-url="http://127.0.0.1:8082/api/mcp/stream?token=8XcdDX1zAjCUfkJTXLYdyBYLLhxyN6BL"
"""
import argparse
import requests
import json
import sys
import os
from vllm import LLM, SamplingParams

# Default model path, can be overridden by env var or just hardcoded as per requirement
DEFAULT_MODEL_PATH = "/Volumes/data/models/qwen/Qwen2.5-0.5B-Instruct"

def get_mcp_tools(mcp_url):
    print(f"\n[1] Fetching tools from MCP at {mcp_url}...")
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
        return mcp_tools
    except Exception as e:
        print(f"Error fetching tools: {e}")
        sys.exit(1)

def convert_to_openai_tools(mcp_tools):
    openai_tools = []
    for tool in mcp_tools:
        openai_tool = {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("inputSchema", {})
            }
        }
        openai_tools.append(openai_tool)
    return openai_tools

def call_mcp_tool(mcp_url, function_name, arguments):
    print(f"Executing tool: {function_name}")
    print(f"Arguments: {arguments}")

    mcp_payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": function_name,
            "arguments": arguments
        },
        "id": 2
    }
    try:
        mcp_response = requests.post(mcp_url, json=mcp_payload)
        mcp_result = mcp_response.json()

        if "result" in mcp_result:
            return json.dumps(mcp_result["result"], ensure_ascii=False)
        elif "error" in mcp_result:
            return json.dumps(mcp_result["error"], ensure_ascii=False)
        else:
            return "Unknown result"
    except Exception as e:
        return f"Error calling tool: {e}"

def main():
    parser = argparse.ArgumentParser(description="Test vLLM with MCP")
    parser.add_argument("--mcp-url", required=True, help="MCP Service URL")
    parser.add_argument("--model-path", default=DEFAULT_MODEL_PATH, help="Path to local model")
    args = parser.parse_args()

    mcp_url = args.mcp_url
    model_path = args.model_path

    # 1. Initialize vLLM
    print(f"Loading model from {model_path}...")
    try:
        llm = LLM(
            model=model_path,
            tensor_parallel_size=1,
            max_model_len=4096,
            tokenizer_mode="slow",
            enforce_eager=True,
            trust_remote_code=True
        )
        tokenizer = llm.get_tokenizer()
    except Exception as e:
        print(f"Failed to load model: {e}")
        sys.exit(1)

    # 2. Fetch Tools
    mcp_tools = get_mcp_tools(mcp_url)
    openai_tools = convert_to_openai_tools(mcp_tools)

    # 3. Prepare Chat
    messages = [
        {"role": "user", "content": "帮我查看一下 talebook 里面有多少本书？"}
    ]

    # Sampling params
    sampling_params = SamplingParams(
        temperature=0.7,
        top_p=0.8,
        max_tokens=512,
        stop=["<|endoftext|>", "<|im_end|>"]
    )

    print("\n[2] Generating response with vLLM...")

    # First turn
    # Qwen2.5 supports 'tools' in apply_chat_template
    prompt = tokenizer.apply_chat_template(
        messages,
        tools=openai_tools,
        add_generation_prompt=True,
        tokenize=False
    )

    outputs = llm.generate([prompt], sampling_params)
    generated_text = outputs[0].outputs[0].text
    print(f"Generated text: {generated_text}")

    # 4. Handle Tool Calls
    # We need to parse the generated text to check for tool calls.
    # Qwen2.5 usually outputs <tool_call>... or similar if using the template.
    # However, the output format depends heavily on the specific template version.
    # Let's try to parse it as a tool call if possible.

    # Simple heuristic: check if it looks like a tool call or if we can parse it.
    # Qwen 2.5 Instruct often produces:
    # <tool_call>
    # {"name": "...", "arguments": {...}}
    # </tool_call>

    tool_calls = []
    if "<tool_call>" in generated_text:
        import re
        # Extract content between <tool_call> and </tool_call>
        matches = re.findall(r"<tool_call>(.*?)</tool_call>", generated_text, re.DOTALL)
        for match in matches:
            try:
                tool_call_data = json.loads(match.strip())
                tool_calls.append(tool_call_data)
            except json.JSONDecodeError:
                print(f"Failed to parse tool call: {match}")

    if tool_calls:
        print(f"\n[3] Tool calls detected: {len(tool_calls)}")

        # Append assistant message
        messages.append({"role": "assistant", "content": generated_text})

        for tool_call in tool_calls:
            func_name = tool_call["name"]
            func_args = tool_call["arguments"]

            # Call MCP
            tool_result = call_mcp_tool(mcp_url, func_name, func_args)
            print(f"Tool result: {tool_result[:200]}...")

            # Append tool result
            messages.append({
                "role": "tool",
                "name": func_name,
                "content": tool_result
            })

        # 5. Follow up
        print("\n[4] Sending follow-up to vLLM...")
        prompt = tokenizer.apply_chat_template(
            messages,
            tools=openai_tools,
            add_generation_prompt=True,
            tokenize=False
        )

        outputs = llm.generate([prompt], sampling_params)
        final_response = outputs[0].outputs[0].text
        print(f"\n[5] Final Answer:\n{final_response}")

    else:
        print("\n[3] No tool calls detected.")
        print(generated_text)

if __name__ == "__main__":
    main()
