# SPDX-FileCopyrightText: 2025 Daniel Eder
# SPDX-FileCopyrightText: 2026 AmariNoa
#
# SPDX-License-Identifier: MIT
#
# Modified by AmariNoa: added tools for partial ticket updates (patch_ticket,
# set_ticket_status, assign_ticket), deletion (delete_ticket, delete_comment,
# delete_timesheet), milestones, project update/membership, comment editing,
# and assorted read helpers. The acting user (bot) is now resolved server-side
# from the API key via whoami (Auth.getUserId) with no ID/email configured;
# LEANTIME_TARGET_USER_EMAIL names the human operating the agent (resolved to
# an ID via email lookup) and is used as the default assignee for tickets the
# bot creates. Credential/session fields are redacted from user responses.

"""Leantime MCP Server - Main server implementation."""

import os
import sys
import json
import logging
from typing import Any, Optional
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
        # Personal Access Token: when set, the client authenticates as the
        # token's human owner (Bearer) instead of the shared API-key bot.
        # Requires the PersonalAccessTokenAuth plugin on the Leantime server.
        leantime_pat = os.getenv("LEANTIME_PAT")

        if not leantime_url:
            raise ValueError(
                "LEANTIME_URL environment variable is required. "
                "Please set it in your .env file or environment."
            )

        if not leantime_api_key and not leantime_pat:
            raise ValueError(
                "Either LEANTIME_API_KEY or LEANTIME_PAT must be set. "
                "Use LEANTIME_API_KEY for the shared bot (e.g. LM Studio), or "
                "LEANTIME_PAT to act as a specific human user."
            )

        leantime_client = LeantimeClient(leantime_url, leantime_api_key, leantime_pat)
        auth_mode = (
            "PAT (acts as the token's user)"
            if leantime_pat
            else "API key (acts as the key's bot user)"
        )
        logger.info(f"Initialized Leantime client for {leantime_url} [auth: {auth_mode}]")

    return leantime_client


async def _acting_user_id(client: LeantimeClient) -> int:
    """Resolve the acting user — the bot that owns the API key.

    Resolved server-side from the API key via Auth.getUserId (whoami), so no
    user ID or email is configured for the acting identity. This is the user
    that authors everything the agent writes.
    """
    return await client.whoami()


async def _target_user_id(client: LeantimeClient) -> Optional[int]:
    """Resolve the configured human "target" user, or None if unset/unknown.

    LEANTIME_TARGET_USER_EMAIL is the email of the person operating the agent
    (their OIDC account). It is resolved to an ID via lookup — the ID is never
    configured directly — and used as the default assignee for tickets the bot
    creates on that person's behalf. Leaving it empty is valid: callers then
    specify the assignee per call (by email or id), e.g. a shared Docker
    deployment where the model picks the target user at call time.
    """
    email = os.getenv("LEANTIME_TARGET_USER_EMAIL")
    if not email:
        return None
    return await client.resolve_email_to_id(email)


class _UnknownEmailError(Exception):
    """Raised when an email cannot be resolved to a user."""


async def _resolve_assignee(
    client: LeantimeClient,
    assigned_to: Optional[int],
    assignee_email: Optional[str],
    use_env_default: bool,
) -> Optional[int]:
    """Resolve a ticket assignee ID from the available inputs.

    Precedence: explicit assignee_email > explicit assigned_to (id) >
    configured LEANTIME_TARGET_USER_EMAIL (only when use_env_default) > None.
    Raises _UnknownEmailError if an explicit email does not map to a user.
    """
    if assignee_email is not None:
        resolved = await client.resolve_email_to_id(assignee_email)
        if resolved is None:
            raise _UnknownEmailError(assignee_email)
        return resolved
    if assigned_to is not None:
        return assigned_to
    if use_env_default:
        return await _target_user_id(client)
    return None


# Sensitive user fields never worth returning over MCP.
_USER_SECRET_FIELDS = (
    "password", "twoFASecret", "session", "sessiontime",
    "pwReset", "pwResetExpiration", "pwResetCount",
)


def _redact_user(user: Any) -> Any:
    """Strip credential/session fields from a user dict (or list of them)."""
    if isinstance(user, list):
        return [_redact_user(u) for u in user]
    if isinstance(user, dict):
        return {k: v for k, v in user.items() if k not in _USER_SECRET_FIELDS}
    return user


def _json(obj: Any) -> str:
    """Serialize a tool result to the JSON string returned over MCP.

    ensure_ascii=False keeps non-ASCII text (e.g. Japanese) as real characters
    rather than \\uXXXX escape sequences. Some local LLMs (e.g. via LM Studio)
    fail to interpret the escaped form when it is handed back to them, so we
    emit the decoded characters directly. The bytes still travel as valid
    JSON/UTF-8 over the wire and round-trip intact.
    """
    return json.dumps(obj, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Write-permission guard (Leantime role-based)
#
# Leantime roles: readonly=5, commenter=10, editor=20, manager=30, admin=40,
# owner=50. Leantime's JSON-RPC API does NOT enforce role-based write
# restrictions (a readonly user can still write via the API), so we enforce it
# here: write/destructive tools run only if the acting user (the API key's
# owner) has a role >= LEANTIME_WRITE_MIN_ROLE (default 20 = editor). Read tools
# are never gated.
# ---------------------------------------------------------------------------
_acting_role: Optional[int] = None


def _write_min_role() -> int:
    """Minimum acting-user role required to perform writes (default 20 = editor)."""
    raw = os.getenv("LEANTIME_WRITE_MIN_ROLE", "20")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 20


async def _acting_user_role(client: LeantimeClient) -> int:
    """Resolve and cache the acting user's Leantime role as an int (0 if unknown)."""
    global _acting_role
    if _acting_role is None:
        uid = await client.whoami()
        user = await client.get_user(uid)
        raw = user.get("role") if isinstance(user, dict) else None
        try:
            _acting_role = int(raw)
        except (TypeError, ValueError):
            _acting_role = 0
    return _acting_role


async def _deny_if_readonly(client: LeantimeClient) -> Optional[str]:
    """Return an error-JSON string if the acting user lacks write permission,
    else None. Call at the start of every write/destructive tool."""
    role = await _acting_user_role(client)
    minimum = _write_min_role()
    if role < minimum:
        return _json({
            "error": "permission_denied",
            "message": (
                f"Write denied: acting Leantime user role is {role}, but >= "
                f"{minimum} is required. This MCP is read-only for this user."
            ),
            "acting_role": role,
            "required_role": minimum,
        })
    return None


# ---------------------------------------------------------------------------
# Attribution: when an AI agent operates this MCP, record which agent produced
# the content. Driven solely by LEANTIME_AGENT_NAME and applied in BOTH auth
# modes (API key and PAT). Currently only comments carry the trailer.
# ---------------------------------------------------------------------------
def _agent_name() -> Optional[str]:
    """The operating AI agent's display name (LEANTIME_AGENT_NAME), or None."""
    name = os.getenv("LEANTIME_AGENT_NAME")
    name = name.strip() if name else ""
    return name or None


def _with_attribution(text: str) -> str:
    """Append a ``Co-Authored-By: <agent>`` trailer to a comment if configured.

    In PAT mode the human is the author, so this marks that an AI agent acted on
    their behalf; in API-key mode it records which AI tool used the shared bot.
    No-op when LEANTIME_AGENT_NAME is unset, or if the trailer is already present.
    """
    name = _agent_name()
    if not name:
        return text
    trailer = f"Co-Authored-By: {name}"
    if trailer in (text or ""):
        return text
    return f"{text}\n\n{trailer}"


# Tool functions will be defined below


@app.tool()
async def get_project(project_id: int) -> str:
    """Get details of a specific project by ID."""
    client = get_client()
    result = await client.get_project(project_id)
    return _json(result)


@app.tool()
async def list_projects() -> str:
    """List all projects accessible to the user."""
    client = get_client()
    result = await client.list_projects()
    return _json(result)


@app.tool()
async def create_project(name: str, details: str = None, clientId: int = None) -> str:
    """Create a new project.

    Accepts ONLY ``name``, ``details`` and ``clientId`` — no other fields. To set
    state, dates, budgets, etc. call ``update_project`` after creating.

    ``clientId`` is optional in this signature but EFFECTIVELY REQUIRED: Leantime
    rejects the call with a ``-32000`` server error when it is omitted. Always
    pass a valid client id — look one up first with ``list_clients`` (a project
    must belong to a client).
    """
    client = get_client()
    denied = await _deny_if_readonly(client)
    if denied:
        return denied
    result = await client.create_project(name=name, details=details, clientId=clientId)
    return _json(result)


@app.tool()
async def get_ticket(ticket_id: int) -> str:
    """Get details of a specific ticket by ID."""
    client = get_client()
    result = await client.get_ticket(ticket_id)
    return _json(result)


@app.tool()
async def list_tickets(project_id: int = None) -> str:
    """List tickets, optionally filtered by project ID."""
    client = get_client()
    result = await client.list_tickets(project_id)
    return _json(result)


@app.tool()
async def create_ticket(headline: str, project_id: int, user_id: int = None, date: str = None,
                       description: str = None, status: str = None, priority: str = None,
                       assignedTo: int = None, assignee_email: str = None,
                       tags: str = None) -> str:
    """Create a new ticket.

    Author (user_id) defaults to the acting bot (whoami) — you normally do not
    pass it.

    Assignee is chosen by precedence: assignee_email (resolved to an id) >
    assignedTo (an id) > the configured LEANTIME_TARGET_USER_EMAIL > none. So
    you can target a person per call by email — useful for a shared deployment
    where LEANTIME_TARGET_USER_EMAIL is left empty and the caller names the
    user each time.
    """
    client = get_client()
    denied = await _deny_if_readonly(client)
    if denied:
        return denied
    if user_id is None:
        user_id = await _acting_user_id(client)
    try:
        assignedTo = await _resolve_assignee(
            client, assignedTo, assignee_email, use_env_default=True
        )
    except _UnknownEmailError as exc:
        return _json(
            {"error": f"Could not resolve a user for {exc}"}
        )
    result = await client.create_ticket(
        headline=headline, project_id=project_id, user_id=user_id, date=date,
        description=description, status=status, priority=priority,
        assignedTo=assignedTo, tags=tags
    )
    return _json(result)


@app.tool()
async def update_ticket(ticket_id: int, project_id: int, headline: str = None, description: str = None, 
                       status: int = None, priority: str = None, assignedTo: int = None) -> str:
    """Update an existing ticket."""
    client = get_client()
    denied = await _deny_if_readonly(client)
    if denied:
        return denied
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
    return _json(result)


@app.tool()
async def get_status_labels() -> str:
    """Get available status labels."""
    client = get_client()
    result = await client.get_status_labels()
    return _json(result)


@app.tool()
async def get_user(user_id: int) -> str:
    """Get details of a specific user by ID."""
    client = get_client()
    result = await client.get_user(user_id)
    return _json(_redact_user(result))


@app.tool()
async def list_users() -> str:
    """List all users."""
    client = get_client()
    result = await client.list_users()
    return _json(_redact_user(result))


@app.tool()
async def add_comment(module: str, module_id: int, comment: str) -> str:
    """Add a comment to a module (ticket, project, etc.)."""
    client = get_client()
    denied = await _deny_if_readonly(client)
    if denied:
        return denied
    result = await client.add_comment(
        module=module, module_id=module_id, comment=_with_attribution(comment)
    )
    return _json(result)


@app.tool()
async def get_comments(module: str, module_id: int) -> str:
    """Get comments for a module (ticket, project, etc.)."""
    client = get_client()
    result = await client.get_comments(module=module, module_id=module_id)
    return _json(result)


@app.tool()
async def add_timesheet(user_id: int, ticket_id: int, hours: float, date: str, description: str = None) -> str:
    """Add a timesheet entry."""
    client = get_client()
    denied = await _deny_if_readonly(client)
    if denied:
        return denied
    result = await client.add_timesheet(
        user_id=user_id, ticket_id=ticket_id, hours=hours, date=date, description=description
    )
    return _json(result)


@app.tool()
async def get_timesheets(project_id: int = None, user_id: int = None) -> str:
    """Get timesheets, optionally filtered by project or user."""
    client = get_client()
    result = await client.get_timesheets(project_id=project_id, user_id=user_id)
    return _json(result)


@app.tool()
async def get_all_subtasks(ticket_id: int) -> str:
    """Get all subtasks for a ticket."""
    client = get_client()
    result = await client.get_all_subtasks(ticket_id)
    return _json(result)


@app.tool()
async def upsert_subtask(parent_ticket: int, headline: str,
                        date: str = None, description: str = None, status: str = None,
                        priority: str = None, assignedTo: str = None, tags: str = None) -> str:
    """Create or update a subtask."""
    client = get_client()
    denied = await _deny_if_readonly(client)
    if denied:
        return denied
    result = await client.upsert_subtask(
        parent_ticket_id=parent_ticket, headline=headline,
        date=date, description=description, status=status, priority=priority,
        assignedTo=assignedTo, tags=tags
    )
    return _json(result)


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
    denied = await _deny_if_readonly(client)
    if denied:
        return denied
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
        return _json({"error": "No fields to update were provided."})
    result = await client.patch_ticket(ticket_id, payload)
    return _json(result)


@app.tool()
async def set_ticket_status(ticket_id: int, status: int) -> str:
    """Change only a ticket's status (thin wrapper over patch_ticket)."""
    client = get_client()
    denied = await _deny_if_readonly(client)
    if denied:
        return denied
    result = await client.patch_ticket(ticket_id, {"status": status})
    return _json(result)


@app.tool()
async def assign_ticket(ticket_id: int, assigned_to: int = None,
                        assignee_email: str = None) -> str:
    """Assign a ticket to a user, by id or by email.

    Provide assignee_email (resolved to an id) or assigned_to (an id). If both
    are given, the email wins.
    """
    client = get_client()
    denied = await _deny_if_readonly(client)
    if denied:
        return denied
    try:
        target = await _resolve_assignee(
            client, assigned_to, assignee_email, use_env_default=False
        )
    except _UnknownEmailError as exc:
        return _json(
            {"error": f"Could not resolve a user for {exc}"}
        )
    if target is None:
        return _json(
            {"error": "Provide assigned_to (id) or assignee_email."}
        )
    result = await client.patch_ticket(ticket_id, {"editorId": target})
    return _json(result)


@app.tool()
async def delete_ticket(ticket_id: int) -> str:
    """Delete a ticket by ID. This is irreversible."""
    client = get_client()
    denied = await _deny_if_readonly(client)
    if denied:
        return denied
    result = await client.delete_ticket(ticket_id)
    return _json(result)


@app.tool()
async def list_my_tickets(project_id: int, user_id: int = None) -> str:
    """List a user's open (not-done) tickets in a project.

    If user_id is omitted, defaults to the acting bot (whoami, resolved from
    the API key). Pass user_id explicitly to query someone else.
    """
    client = get_client()
    if user_id is None:
        try:
            user_id = await _acting_user_id(client)
        except ValueError as exc:
            return _json({"error": str(exc)})
    result = await client.get_open_user_tickets(user_id=user_id, project_id=project_id)
    return _json(result)


@app.tool()
async def list_milestones(project_id: int) -> str:
    """List milestones for a project."""
    client = get_client()
    result = await client.list_milestones(project_id)
    return _json(result)


@app.tool()
async def create_milestone(headline: str, project_id: int, user_id: int,
                           date: str = None, tags: str = None) -> str:
    """Create a milestone (a ticket of type 'milestone') in a project."""
    client = get_client()
    denied = await _deny_if_readonly(client)
    if denied:
        return denied
    extra = {}
    if tags is not None:
        extra["tags"] = tags
    result = await client.create_milestone(
        headline=headline, project_id=project_id, user_id=user_id, date=date, **extra
    )
    return _json(result)


@app.tool()
async def edit_comment(comment_id: int, comment: str) -> str:
    """Edit the text of an existing comment."""
    client = get_client()
    denied = await _deny_if_readonly(client)
    if denied:
        return denied
    result = await client.edit_comment(comment_id=comment_id, comment=comment)
    return _json(result)


@app.tool()
async def delete_comment(comment_id: int) -> str:
    """Delete a comment by ID."""
    client = get_client()
    denied = await _deny_if_readonly(client)
    if denied:
        return denied
    result = await client.delete_comment(comment_id)
    return _json(result)


@app.tool()
async def update_project(project_id: int, name: str = None, details: str = None,
                         clientId: int = None, fields: dict = None) -> str:
    """Update an existing project's fields (only those provided are changed)."""
    client = get_client()
    denied = await _deny_if_readonly(client)
    if denied:
        return denied
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
        return _json({"error": "No fields to update were provided."})
    result = await client.update_project(project_id, payload)
    return _json(result)


@app.tool()
async def list_project_users(project_id: int) -> str:
    """List the users assigned to a project."""
    client = get_client()
    result = await client.list_project_users(project_id)
    return _json(result)


@app.tool()
async def assign_user_to_project(user_id: int, project_id: int) -> str:
    """Assign a user to a project (add them as a project member).

    Pass a SINGLE ``user_id`` and ``project_id`` per call — do NOT pass a list of
    project ids. Leantime stores assignments as the user's full project set, but
    this tool computes that union internally (read-merge-write), so you only name
    the one project to add.

    Idempotent: if the user is already a member, nothing changes. The user's
    OTHER project assignments are preserved — it reads the current set and adds
    this project rather than replacing it. The new membership gets an empty
    project role; existing roles are left untouched. Returns the resulting status
    and the user's full list of assigned project IDs.
    """
    client = get_client()
    denied = await _deny_if_readonly(client)
    if denied:
        return denied
    result = await client.assign_user_to_project(user_id, project_id)
    return _json(result)


@app.tool()
async def delete_timesheet(timesheet_id: int) -> str:
    """Delete a timesheet entry by ID. (Leantime has no update; delete + re-add.)"""
    client = get_client()
    denied = await _deny_if_readonly(client)
    if denied:
        return denied
    result = await client.delete_timesheet(timesheet_id)
    return _json(result)


@app.tool()
async def get_ticket_types() -> str:
    """Get the available ticket types (task, story, bug, etc.)."""
    client = get_client()
    result = await client.get_ticket_types()
    return _json(result)


@app.tool()
async def get_priority_labels() -> str:
    """Get the available priority IDs mapped to their labels."""
    client = get_client()
    result = await client.get_priority_labels()
    return _json(result)


@app.tool()
async def get_current_user() -> str:
    """Get the acting user — the bot that owns the API key (via whoami)."""
    client = get_client()
    try:
        user_id = await _acting_user_id(client)
    except ValueError as exc:
        return _json({"error": str(exc)})
    result = await client.get_user(user_id)
    return _json(_redact_user(result))


@app.tool()
async def get_target_user() -> str:
    """Get the configured human target user (LEANTIME_TARGET_USER_EMAIL).

    This is the person operating the agent (their OIDC account), resolved from
    the configured email — used as the default assignee for tickets the bot
    creates. Returns an error object if the email is unset or unknown.
    """
    client = get_client()
    email = os.getenv("LEANTIME_TARGET_USER_EMAIL")
    if not email:
        return _json(
            {"error": "LEANTIME_TARGET_USER_EMAIL is not set."}
        )
    user_id = await _target_user_id(client)
    if user_id is None:
        return _json(
            {"error": f"Could not resolve a user for {email}"}
        )
    result = await client.get_user(user_id)
    return _json(_redact_user(result))


@app.tool()
async def resolve_user(email: str) -> str:
    """Resolve an email address to a user (id + safe profile fields).

    Useful for picking a ticket assignee by email at call time, e.g. when no
    LEANTIME_TARGET_USER_EMAIL is configured. Credential/session fields are
    stripped. Returns an error object if the email maps to no user.
    """
    client = get_client()
    user_id = await client.resolve_email_to_id(email)
    if user_id is None:
        return _json(
            {"error": f"Could not resolve a user for {email}"}
        )
    result = await client.get_user(user_id)
    return _json(_redact_user(result))


# ---------------------------------------------------------------------------
# Clients (the companies/organisations that own projects). create/update/delete
# are role-gated like every other write tool. Recognised client columns: name
# (required), street, zip, city, state, country, phone, internet (website),
# email.
# ---------------------------------------------------------------------------
@app.tool()
async def list_clients() -> str:
    """List all clients (id, name, website, number of projects)."""
    client = get_client()
    result = await client.list_clients()
    return _json(result)


@app.tool(name="get_client")
async def get_client_details(client_id: int) -> str:
    """Get full details of a single client by ID (name, address, contact)."""
    client = get_client()
    result = await client.get_client(client_id)
    return _json(result)


@app.tool()
async def create_client(name: str, street: str = None, zip: str = None,
                        city: str = None, state: str = None, country: str = None,
                        phone: str = None, internet: str = None,
                        email: str = None) -> str:
    """Create a new client (company).

    Only ``name`` is required; ``internet`` is the website URL. Leantime rejects
    an empty or duplicate name. Returns the new client's ID.
    """
    client = get_client()
    denied = await _deny_if_readonly(client)
    if denied:
        return denied
    result = await client.create_client(
        name=name, street=street, zip=zip, city=city, state=state,
        country=country, phone=phone, internet=internet, email=email,
    )
    return _json(result)


@app.tool()
async def update_client(client_id: int, name: str = None, street: str = None,
                        zip: str = None, city: str = None, state: str = None,
                        country: str = None, phone: str = None,
                        internet: str = None, email: str = None) -> str:
    """Update a client, changing ONLY the fields you pass.

    Unspecified fields are preserved: the tool reads the current client and
    merges your changes before saving (Leantime's client edit otherwise blanks
    omitted fields). ``internet`` is the website URL.
    """
    client = get_client()
    denied = await _deny_if_readonly(client)
    if denied:
        return denied
    fields = {
        "name": name, "street": street, "zip": zip, "city": city,
        "state": state, "country": country, "phone": phone,
        "internet": internet, "email": email,
    }
    fields = {key: value for key, value in fields.items() if value is not None}
    if not fields:
        return _json({"error": "No fields to update were provided."})
    result = await client.update_client(client_id, fields)
    return _json(result)


@app.tool()
async def delete_client(client_id: int) -> str:
    """Delete a client by ID. This is IRREVERSIBLE.

    WARNING: deleting a client also deletes ALL of its projects (and their
    tickets) in Leantime. Double-check the client_id before calling.
    """
    client = get_client()
    denied = await _deny_if_readonly(client)
    if denied:
        return denied
    result = await client.delete_client(client_id)
    return _json(result)


def main():
    """Main entry point for the MCP server."""
    app.run()


if __name__ == "__main__":
    main()
