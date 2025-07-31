#!/usr/bin/env python3
"""
Test script for Streamable MCP Server using standard MCP HTTP transport.

This script tests the initialization and tools functionality of the
streamable server implementation without directly calling internal code.
"""

import asyncio
import json
import httpx
from typing import Dict, Any


class MCPClient:
    """A simple MCP client for testing the HTTP server."""

    def __init__(self, base_url: str = "http://localhost:3000/api/mcp"):
        self.base_url = base_url
        self.client = httpx.AsyncClient()
        self.request_id = 1

    async def send_request(self, method: str, params: Dict[Any, Any] = None) -> Dict[Any, Any]:
        """Send an MCP request to the server."""
        request_data = {
            "jsonrpc": "2.0",
            "id": self.request_id,
            "method": method,
        }

        if params:
            request_data["params"] = params

        self.request_id += 1

        try:
            response = await self.client.post(
                f"{self.base_url}/stream",
                json=request_data,
                headers={"Content-Type": "application/json"}
            )
            return response.json()
        except Exception as e:
            print(f"Error sending request: {e}")
            return {"error": str(e)}

    async def initialize(self) -> Dict[Any, Any]:
        """Send initialize request to MCP server."""
        return await self.send_request("initialize", {
            "protocolVersion": "2024-01-01",
            "capabilities": {},
            "clientInfo": {
                "name": "mcp-test-client",
                "version": "1.0.0"
            }
        })

    async def list_tools(self) -> Dict[Any, Any]:
        """Send tools/list request to MCP server."""
        return await self.send_request("tools/list")

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()


async def test_server_initialization(client: MCPClient):
    """Test server initialization."""
    print("=== Testing Server Initialization ===")

    try:
        response = await client.initialize()
        print(f"✓ Initialization response received")

        if "result" in response:
            print(f"✓ Server name: {response['result'].get('serverInfo', {}).get('name', 'Unknown')}")
            print(f"✓ Protocol version: {response['result'].get('protocolVersion', 'Unknown')}")
            return True
        else:
            print(f"✗ Initialization failed: {response}")
            return False

    except Exception as e:
        print(f"✗ Initialization error: {e}")
        return False


async def test_tools_functionality(client: MCPClient):
    """Test tools functionality."""
    print("\n=== Testing Tools Functionality ===")

    try:
        # List available tools
        response = await client.list_tools()
        print(f"✓ Tools list response received")

        if "result" in response and "tools" in response["result"]:
            tools = response["result"]["tools"]
            print(f"✓ Found {len(tools)} tools")

            # Show first few tools
            for i, tool in enumerate(tools):
                print(f"  {i+1}. {tool.get('name', 'Unknown')}: {tool.get('description', 'No description')}")

            return True
        else:
            print(f"✗ Failed to get tools list: {response}")
            return False

    except Exception as e:
        print(f"✗ Tools functionality error: {e}")
        return False


async def test_server_health(client: MCPClient):
    """Test server health endpoint."""
    print("\n=== Testing Server Health ===")

    try:
        response = await client.client.get(f"{client.base_url}/health")
        data = response.json()
        print(f"✓ Health check response: {data}")

        if data.get("status") == "healthy":
            print("✓ Server is healthy")
            return True
        else:
            print("✗ Server is not healthy")
            return False

    except Exception as e:
        print(f"✗ Health check error: {e}")
        return False


async def main():
    """Main test function."""
    print("Starting MCP Streamable Server Test...\n")

    client = MCPClient()

    try:
        # Test server health
        health_ok = await test_server_health(client)
        if not health_ok:
            print("\n⚠️  Server health check failed. Server might not be running.")
            print("Please make sure the server is running on localhost:3001")
            return

        # Test initialization
        init_ok = await test_server_initialization(client)
        if not init_ok:
            print("\n✗ Server initialization test failed")
            return

        # Test tools
        tools_ok = await test_tools_functionality(client)
        if not tools_ok:
            print("\n✗ Tools functionality test failed")
            return

        print("\n=== All Tests Completed ===")
        print("✓ Server health check: PASSED")
        print("✓ Server initialization: PASSED")
        print("✓ Tools functionality: PASSED")
        print("\n🎉 All tests passed!")

    except Exception as e:
        print(f"\n✗ Unexpected error during testing: {e}")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
