# SPDX-FileCopyrightText: 2025 Daniel Eder
#
# SPDX-License-Identifier: MIT

"""Leantime MCP Server - Main server implementation."""

import os
import sys
import json
import logging
from typing import Any
from dotenv import load_dotenv

from mcp.server import Server
from mcp.types import Tool, TextContent

from .client import LeantimeClient, LeantimeAPIError
from .tools import get_tools

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Initialize the MCP server
app = Server("leantime-mcp")

# Global Leantime client instance
leantime_client: LeantimeClient = None


def get_client() -> LeantimeClient:
    """Get or create the Leantime client instance."""
    global leantime_client
    
    if leantime_client is None:
        # Get configuration from environment
        leantime_url = os.getenv("LEANTIME_URL")
        leantime_api_key = os.getenv("LEANTIME_API_KEY")
        leantime_user_email = os.getenv("LEANTIME_USER_EMAIL")
        
        if not leantime_url:
            raise ValueError(
                "LEANTIME_URL environment variable is required. "
                "Please set it in your .env file or environment."
            )
        
        if not leantime_api_key:
            raise ValueError(
                "LEANTIME_API_KEY environment variable is required. "
                "Please set it in your .env file or environment."
            )
        
        if not leantime_user_email:
            raise ValueError(
                "LEANTIME_USER_EMAIL environment variable is required. "
                "Please set it in your .env file or environment."
            )
        
        leantime_client = LeantimeClient(leantime_url, leantime_api_key)
        logger.info(f"Initialized Leantime client for {leantime_url}")
    
    return leantime_client


@app.list_tools()
async def list_tools() -> list[Tool]:
    """List all available Leantime MCP tools."""
    return get_tools()


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle tool calls by routing to appropriate Leantime API methods."""
    try:
        client = get_client()
        result = None
        
        # Route tool calls to appropriate client methods
        if name == "get_project":
            result = await client.get_project(arguments["project_id"])
        
        elif name == "list_projects":
            result = await client.list_projects()
        
        elif name == "create_project":
            result = await client.create_project(
                name=arguments["name"],
                details=arguments.get("details"),
                clientId=arguments.get("clientId")
            )
        
        elif name == "get_ticket":
            result = await client.get_ticket(arguments["ticket_id"])
        
        elif name == "list_tickets":
            result = await client.list_tickets(arguments.get("project_id"))
        
        elif name == "create_ticket":
            result = await client.create_ticket(
                headline=arguments["headline"],
                project_id=arguments["project_id"],
                user_id=arguments["user_id"],
                date=arguments.get("date"),
                description=arguments.get("description"),
                status=arguments.get("status"),
                priority=arguments.get("priority"),
                assignedTo=arguments.get("assignedTo")
            )
        
        elif name == "update_ticket":
            ticket_id = arguments.pop("ticket_id")
            project_id = arguments.pop("project_id")
            result = await client.update_ticket(ticket_id, project_id, **arguments)
        
        elif name == "get_status_labels":
            result = await client.get_status_labels()
        
        elif name == "get_user":
            result = await client.get_user(arguments["user_id"])
        
        elif name == "list_users":
            result = await client.list_users()
        
        elif name == "add_comment":
            result = await client.add_comment(
                module=arguments["module"],
                module_id=arguments["module_id"],
                comment=arguments["comment"]
            )
        
        elif name == "get_comments":
            result = await client.get_comments(
                module=arguments["module"],
                module_id=arguments["module_id"]
            )
        
        elif name == "add_timesheet":
            result = await client.add_timesheet(
                user_id=arguments["user_id"],
                ticket_id=arguments["ticket_id"],
                hours=arguments["hours"],
                date=arguments["date"],
                description=arguments.get("description")
            )
        
        elif name == "get_timesheets":
            result = await client.get_timesheets(
                project_id=arguments.get("project_id"),
                user_id=arguments.get("user_id")
            )
        
        else:
            return [TextContent(
                type="text",
                text=f"Unknown tool: {name}"
            )]
        
        # Format and return the result
        return [TextContent(
            type="text",
            text=json.dumps(result, indent=2)
        )]
    
    except LeantimeAPIError as e:
        logger.error(f"Leantime API error: {e}")
        return [TextContent(
            type="text",
            text=f"Leantime API Error ({e.code}): {e.message}"
        )]
    
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        return [TextContent(
            type="text",
            text=f"Configuration Error: {str(e)}"
        )]
    
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        return [TextContent(
            type="text",
            text=f"Error: {str(e)}"
        )]


def main():
    """Main entry point for the MCP server."""
    import asyncio
    from mcp.server.stdio import stdio_server
    
    async def run():
        async with stdio_server() as (read_stream, write_stream):
            await app.run(
                read_stream,
                write_stream,
                app.create_initialization_options()
            )
    
    asyncio.run(run())


if __name__ == "__main__":
    main()
