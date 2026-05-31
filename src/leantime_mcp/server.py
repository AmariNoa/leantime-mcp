# SPDX-FileCopyrightText: 2025 Daniel Eder
# SPDX-FileCopyrightText: 2026 AmariNoa
#
# SPDX-License-Identifier: MIT
#
# Modified by AmariNoa: added tools for partial ticket updates (patch_ticket,
# set_ticket_status, assign_ticket), deletion (delete_ticket, delete_comment,
# delete_timesheet), milestones, project update/membership, comment editing,
# and assorted read helpers.

"""Leantime MCP Server - Main server implementation."""

import os
import sys
import json
import logging
from typing import Any
from dotenv import load_dotenv

from fastmcp import FastMCP

from leantime_mcp.client import LeantimeClient, LeantimeAPIError

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Initialize the FastMCP server
app = FastMCP("leantime-mcp")

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


# Tool functions will be defined below


@app.tool()
async def get_project(project_id: int) -> str:
    """Get details of a specific project by ID."""
    client = get_client()
    result = await client.get_project(project_id)
    return json.dumps(result, indent=2)


@app.tool()
async def list_projects() -> str:
    """List all projects accessible to the user."""
    client = get_client()
    result = await client.list_projects()
    return json.dumps(result, indent=2)


@app.tool()
async def create_project(name: str, details: str = None, clientId: int = None) -> str:
    """Create a new project."""
    client = get_client()
    result = await client.create_project(name=name, details=details, clientId=clientId)
    return json.dumps(result, indent=2)


@app.tool()
async def get_ticket(ticket_id: int) -> str:
    """Get details of a specific ticket by ID."""
    client = get_client()
    result = await client.get_ticket(ticket_id)
    return json.dumps(result, indent=2)


@app.tool()
async def list_tickets(project_id: int = None) -> str:
    """List tickets, optionally filtered by project ID."""
    client = get_client()
    result = await client.list_tickets(project_id)
    return json.dumps(result, indent=2)


@app.tool()
async def create_ticket(headline: str, project_id: int, user_id: int, date: str = None, 
                       description: str = None, status: str = None, priority: str = None,
                       assignedTo: str = None, tags: str = None) -> str:
    """Create a new ticket."""
    client = get_client()
    result = await client.create_ticket(
        headline=headline, project_id=project_id, user_id=user_id, date=date,
        description=description, status=status, priority=priority,
        assignedTo=assignedTo, tags=tags
    )
    return json.dumps(result, indent=2)


@app.tool()
async def update_ticket(ticket_id: int, project_id: int, headline: str = None, description: str = None, 
                       status: int = None, priority: str = None, assignedTo: int = None) -> str:
    """Update an existing ticket."""
    client = get_client()
    # Build kwargs from non-None parameters
    kwargs = {}
    if headline is not None:
        kwargs['headline'] = headline
    if description is not None:
        kwargs['description'] = description
    if status is not None:
        kwargs['status'] = status
    if priority is not None:
        kwargs['priority'] = priority
    if assignedTo is not None:
        kwargs['assignedTo'] = assignedTo
    
    result = await client.update_ticket(ticket_id, project_id, **kwargs)
    return json.dumps(result, indent=2)


@app.tool()
async def get_status_labels() -> str:
    """Get available status labels."""
    client = get_client()
    result = await client.get_status_labels()
    return json.dumps(result, indent=2)


@app.tool()
async def get_user(user_id: int) -> str:
    """Get details of a specific user by ID."""
    client = get_client()
    result = await client.get_user(user_id)
    return json.dumps(result, indent=2)


@app.tool()
async def list_users() -> str:
    """List all users."""
    client = get_client()
    result = await client.list_users()
    return json.dumps(result, indent=2)


@app.tool()
async def add_comment(module: str, module_id: int, comment: str) -> str:
    """Add a comment to a module (ticket, project, etc.)."""
    client = get_client()
    result = await client.add_comment(module=module, module_id=module_id, comment=comment)
    return json.dumps(result, indent=2)


@app.tool()
async def get_comments(module: str, module_id: int) -> str:
    """Get comments for a module (ticket, project, etc.)."""
    client = get_client()
    result = await client.get_comments(module=module, module_id=module_id)
    return json.dumps(result, indent=2)


@app.tool()
async def add_timesheet(user_id: int, ticket_id: int, hours: float, date: str, description: str = None) -> str:
    """Add a timesheet entry."""
    client = get_client()
    result = await client.add_timesheet(
        user_id=user_id, ticket_id=ticket_id, hours=hours, date=date, description=description
    )
    return json.dumps(result, indent=2)


@app.tool()
async def get_timesheets(project_id: int = None, user_id: int = None) -> str:
    """Get timesheets, optionally filtered by project or user."""
    client = get_client()
    result = await client.get_timesheets(project_id=project_id, user_id=user_id)
    return json.dumps(result, indent=2)


@app.tool()
async def get_all_subtasks(ticket_id: int) -> str:
    """Get all subtasks for a ticket."""
    client = get_client()
    result = await client.get_all_subtasks(ticket_id)
    return json.dumps(result, indent=2)


@app.tool()
async def upsert_subtask(parent_ticket: int, headline: str,
                        date: str = None, description: str = None, status: str = None,
                        priority: str = None, assignedTo: str = None, tags: str = None) -> str:
    """Create or update a subtask."""
    client = get_client()
    result = await client.upsert_subtask(
        parent_ticket_id=parent_ticket, headline=headline,
        date=date, description=description, status=status, priority=priority,
        assignedTo=assignedTo, tags=tags
    )
    return json.dumps(result, indent=2)


# Map friendly tool argument names to Leantime's actual ticket columns.
_TICKET_FIELD_MAP = {
    "status": "status",
    "headline": "headline",
    "description": "description",
    "priority": "priority",
    "assigned_to": "editorId",
    "milestone_id": "milestoneid",
    "due_date": "dateToFinish",
    "tags": "tags",
}


@app.tool()
async def patch_ticket(ticket_id: int, status: int = None, headline: str = None,
                       description: str = None, priority: int = None,
                       assigned_to: int = None, milestone_id: int = None,
                       due_date: str = None, tags: str = None,
                       fields: dict = None) -> str:
    """Partially update a ticket, changing ONLY the fields you pass.

    Prefer this over update_ticket: update_ticket re-saves the whole ticket and
    blanks any field you omit, whereas patch_ticket touches only the provided
    fields and leaves everything else intact.

    Args:
        ticket_id: ID of the ticket to update.
        status: New status ID (see get_status_labels).
        headline: New title.
        description: New description.
        priority: New priority ID (see get_priority_labels).
        assigned_to: User ID to assign the ticket to (Leantime editorId).
        milestone_id: ID of the milestone to attach the ticket to.
        due_date: Due date, YYYY-MM-DD.
        tags: Comma-separated tags.
        fields: Advanced escape hatch — a dict of raw Leantime column names to
            values, merged last (overrides the named args above).
    """
    client = get_client()
    payload = {}
    named = {
        "status": status, "headline": headline, "description": description,
        "priority": priority, "assigned_to": assigned_to,
        "milestone_id": milestone_id, "due_date": due_date, "tags": tags,
    }
    for key, value in named.items():
        if value is not None:
            payload[_TICKET_FIELD_MAP[key]] = value
    if fields:
        payload.update(fields)
    if not payload:
        return json.dumps({"error": "No fields to update were provided."}, indent=2)
    result = await client.patch_ticket(ticket_id, payload)
    return json.dumps(result, indent=2)


@app.tool()
async def set_ticket_status(ticket_id: int, status: int) -> str:
    """Change only a ticket's status (thin wrapper over patch_ticket)."""
    client = get_client()
    result = await client.patch_ticket(ticket_id, {"status": status})
    return json.dumps(result, indent=2)


@app.tool()
async def assign_ticket(ticket_id: int, assigned_to: int) -> str:
    """Assign a ticket to a user (thin wrapper over patch_ticket)."""
    client = get_client()
    result = await client.patch_ticket(ticket_id, {"editorId": assigned_to})
    return json.dumps(result, indent=2)


@app.tool()
async def delete_ticket(ticket_id: int) -> str:
    """Delete a ticket by ID. This is irreversible."""
    client = get_client()
    result = await client.delete_ticket(ticket_id)
    return json.dumps(result, indent=2)


@app.tool()
async def list_my_tickets(project_id: int, user_id: int = None) -> str:
    """List a user's open (not-done) tickets in a project.

    Pass user_id explicitly for reliable results. If omitted, it falls back to
    the user mapped to LEANTIME_USER_EMAIL, which may NOT be the API token's
    acting user (e.g. the token may act as a dedicated agent account while the
    configured email belongs to a human admin).
    """
    client = get_client()
    if user_id is None:
        email = os.getenv("LEANTIME_USER_EMAIL")
        me = await client.get_user_by_email(email)
        user_id = me.get("id") if isinstance(me, dict) else None
        if user_id is None:
            return json.dumps(
                {"error": f"Could not resolve user_id for {email}"}, indent=2
            )
    result = await client.get_open_user_tickets(user_id=user_id, project_id=project_id)
    return json.dumps(result, indent=2)


@app.tool()
async def list_milestones(project_id: int) -> str:
    """List milestones for a project."""
    client = get_client()
    result = await client.list_milestones(project_id)
    return json.dumps(result, indent=2)


@app.tool()
async def create_milestone(headline: str, project_id: int, user_id: int,
                           date: str = None, tags: str = None) -> str:
    """Create a milestone (a ticket of type 'milestone') in a project."""
    client = get_client()
    extra = {}
    if tags is not None:
        extra["tags"] = tags
    result = await client.create_milestone(
        headline=headline, project_id=project_id, user_id=user_id, date=date, **extra
    )
    return json.dumps(result, indent=2)


@app.tool()
async def edit_comment(comment_id: int, comment: str) -> str:
    """Edit the text of an existing comment."""
    client = get_client()
    result = await client.edit_comment(comment_id=comment_id, comment=comment)
    return json.dumps(result, indent=2)


@app.tool()
async def delete_comment(comment_id: int) -> str:
    """Delete a comment by ID."""
    client = get_client()
    result = await client.delete_comment(comment_id)
    return json.dumps(result, indent=2)


@app.tool()
async def update_project(project_id: int, name: str = None, details: str = None,
                         clientId: int = None, fields: dict = None) -> str:
    """Update an existing project's fields (only those provided are changed)."""
    client = get_client()
    payload = {}
    if name is not None:
        payload["name"] = name
    if details is not None:
        payload["details"] = details
    if clientId is not None:
        payload["clientId"] = clientId
    if fields:
        payload.update(fields)
    if not payload:
        return json.dumps({"error": "No fields to update were provided."}, indent=2)
    result = await client.update_project(project_id, payload)
    return json.dumps(result, indent=2)


@app.tool()
async def list_project_users(project_id: int) -> str:
    """List the users assigned to a project."""
    client = get_client()
    result = await client.list_project_users(project_id)
    return json.dumps(result, indent=2)


@app.tool()
async def delete_timesheet(timesheet_id: int) -> str:
    """Delete a timesheet entry by ID. (Leantime has no update; delete + re-add.)"""
    client = get_client()
    result = await client.delete_timesheet(timesheet_id)
    return json.dumps(result, indent=2)


@app.tool()
async def get_ticket_types() -> str:
    """Get the available ticket types (task, story, bug, etc.)."""
    client = get_client()
    result = await client.get_ticket_types()
    return json.dumps(result, indent=2)


@app.tool()
async def get_priority_labels() -> str:
    """Get the available priority IDs mapped to their labels."""
    client = get_client()
    result = await client.get_priority_labels()
    return json.dumps(result, indent=2)


@app.tool()
async def get_current_user() -> str:
    """Get the acting user (resolved from the configured LEANTIME_USER_EMAIL)."""
    client = get_client()
    email = os.getenv("LEANTIME_USER_EMAIL")
    result = await client.get_user_by_email(email)
    return json.dumps(result, indent=2)


def main():
    """Main entry point for the MCP server."""
    app.run()


if __name__ == "__main__":
    main()
