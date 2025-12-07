import sys
import os
import shutil
import asyncio
from typing import Dict, Any, Literal
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# 1. DEFINE ABSOLUTE PATHS
# Use 'mcp_server' if that is your folder name
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
COMMON_SCRIPT = os.path.join(BASE_DIR, "mcp_server", "common.py") 
ATLAS_SCRIPT = os.path.join(BASE_DIR, "mcp_server", "atlas.py")

# 2. DETECT UV (Since you are using it)
UV_PATH = shutil.which("uv")

class InvoiceMCPClient:
    def __init__(self):
        self.servers = {}
        
        # Helper to construct command
        def get_params(script_path):
            if not os.path.exists(script_path):
                print(f"❌ CRITICAL ERROR: Script not found at {script_path}")
            
            # If using 'uv', use it to run the script. 
            # This ensures dependencies (like aiosqlite/fastmcp) are found.
            if UV_PATH:
                return StdioServerParameters(
                    command=UV_PATH,
                    args=["run", script_path],
                    env=os.environ.copy()
                )
            else:
                # Fallback to standard python
                return StdioServerParameters(
                    command=sys.executable,
                    args=[script_path],
                    env=os.environ.copy()
                )

        self.servers["COMMON"] = get_params(COMMON_SCRIPT)
        self.servers["ATLAS"] = get_params(ATLAS_SCRIPT)

    async def route(self, server_name: Literal["COMMON", "ATLAS"], tool_name: str, arguments: Dict[str, Any] = {}) -> Any:
        if server_name not in self.servers:
            raise ValueError(f"Unknown server: {server_name}")

        server_params = self.servers[server_name]
        
        # Debug print
        print(f"🔌 Starting Subprocess: {server_params.command} {' '.join(server_params.args)}")

        try:
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    
                    try:
                        result = await session.call_tool(tool_name, arguments)
                        
                        if not result.content:
                            return None
                        return result.content[0].text
                        
                    except Exception as tool_err:
                        # This catches errors INSIDE the tool (like DB errors)
                        print(f"❌ Tool Execution Error: {tool_err}")
                        return str(tool_err)

        except Exception as conn_err:
            # This catches errors STARTING the server (like path issues)
            print(f"❌ Connection Error (Server didn't start?): {conn_err}")
            return {"status": "error", "message": str(conn_err)}

mcp_client = InvoiceMCPClient()