<!--
SPDX-FileCopyrightText: 2025 Daniel Eder

SPDX-License-Identifier: CC0-1.0
-->

# Leantime MCP Server

> **Fork notice:** This is a fork of [daniel-eder/leantime-mcp](https://github.com/daniel-eder/leantime-mcp) (MIT). It adds a fix for the `add_comment` / `get_comments` tools, whose JSON-RPC parameters did not match Leantime's `Comments` service signatures and failed with `-32602 Invalid params`. The parameters are now sent as `entityId` (instead of `moduleId`) and the comment text as `values.text`. This fork also adds tools for partial ticket updates (`patch_ticket`), deletion (`delete_ticket`, `delete_comment`, `delete_timesheet`), milestones, project updates/membership, comment editing, and assorted read helpers. Tool responses are now serialized with `ensure_ascii=False` so non-ASCII text (e.g. Japanese) is returned as real characters rather than `\uXXXX` escape sequences, which some local LLMs could not interpret. It also adds a role-based write guard: write/destructive tools are gated by the acting user's Leantime role (`LEANTIME_WRITE_MIN_ROLE`, default editor=20), so an API key owned by a low-role user is effectively read-only — Leantime's API does not enforce this on its own (see [Write permissions](#write-permissions-read-only-enforcement)). All original copyrights and the MIT license are retained.

A Model Context Protocol (MCP) server that provides AI assistants with access to Leantime's (leantime.io) JsonRPC 2.0 API. This enables AI tools like Claude to interact with Leantime projects, tickets, timesheets, users, and more through a standardized interface.

This server uses [FastMCP](https://github.com/jlowin/fastmcp) which supports multiple transport protocols including stdio, HTTP, WebSocket, and SSE, making it suitable for various deployment scenarios.

The leantime mcp plugin is not needed.
If you own the leantime mcp plugin consider using https://github.com/Leantime/php-mcp-server instead.

## MCP Client Configuration

This project uses [uv](https://github.com/astral-sh/uv) for fast, reliable Python package management. Ensure it is installed before modifying your MCP settings.

To use with Claude Desktop or other MCP clients, add to your MCP settings:

### STDIO Transport (Default)

For local MCP clients like Claude Desktop that communicate via standard input/output:

```json
{
  "mcpServers": {
    "leantime": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/AmariNoa/leantime-mcp.git",
        "leantime-mcp"
      ],
      "env": {
        "LEANTIME_URL": "https://your-leantime-instance.com",
        "LEANTIME_API_KEY": "your_api_key_here",
        "LEANTIME_TARGET_USER_EMAIL": "person-operating-the-agent@example.com"
      }
    }
  }
}
```

### HTTP Transport

For remote HTTP connections, first start the server with HTTP transport (see [Running the Server](#running-the-server)), then configure your MCP client to connect to the HTTP endpoint:

```json
{
  "mcpServers": {
    "leantime-http": {
      "url": "http://localhost:8000/mcp",
      "transport": "streamableHttp"
    }
  }
}
```

**Note:** The HTTP transport configuration depends on your MCP client's support for HTTP connections. The server must be running separately using the `fastmcp run` command with `--transport http` option. Make sure to set the required environment variables (`LEANTIME_URL`, `LEANTIME_API_KEY`, and optionally `LEANTIME_TARGET_USER_EMAIL`) when starting the HTTP server.

### Identity model: the bot vs. the human target

There are two distinct identities, and **neither is configured as a user ID**:

1. **The acting user (the bot).** Resolved server-side from the API key via whoami (`Auth.getUserId`) — no ID or email is configured for it. This is the user that **authored** everything the agent writes (the API key's owner) and the default for `get_current_user` / `list_my_tickets`. Its access scope is whatever the key's role and assigned projects allow, enforced by Leantime.

2. **The human target (optional).** `LEANTIME_TARGET_USER_EMAIL` is the email of the person operating the agent (their OIDC account). It is resolved to an ID via lookup — never set directly — and used as the **default assignee** for tickets the bot creates on that person's behalf. Inspect it with `get_target_user`. If unset, created tickets simply have no default assignee.

**Per-call targeting.** You don't have to configure the target at all. `create_ticket` and `assign_ticket` accept an `assignee_email` argument that is resolved to a user ID at call time, and `resolve_user(email)` looks up a user by email on demand. This suits a shared deployment (e.g. one Docker container behind LM Studio) where `LEANTIME_TARGET_USER_EMAIL` is left empty and the caller names the target user per request. Assignee precedence: `assignee_email` > `assignedTo`/`assigned_to` (an id) > `LEANTIME_TARGET_USER_EMAIL` > none.

Credential and session fields are stripped from all user responses.

> **Per-user deployment:** generating a Leantime API key auto-creates a bot user (`source=api`, Editor role) that owns the key. For each person, issue a dedicated key (scoped to the right role/projects) and set `LEANTIME_API_KEY` to it plus `LEANTIME_TARGET_USER_EMAIL` to that person's email. The bot identifies itself via the key; the human is resolved from the email — so the same config shape works for everyone with no user IDs to manage.

## Getting a Leantime API Key

1. Log in to your Leantime instance
2. Go to Company -> API Keys 
3. Generate a new API key

## Running the Server

This server supports multiple transport protocols for different deployment scenarios:

### STDIO Transport (Default)

For use with MCP clients like Claude Desktop that communicate via standard input/output:

```bash
# Using the entry point
leantime-mcp

# Or run directly
python -m src.leantime_mcp.server
```

### HTTP Transport

For remote access via HTTP, useful for web services and remote clients:

```bash
# Run on default port 8000
fastmcp run src/leantime_mcp/server.py:app --transport http

# Run on custom port
fastmcp run src/leantime_mcp/server.py:app --transport http --port 9000

# When developing (without installing the package), use uv run:
uv run fastmcp run src/leantime_mcp/server.py:app --transport http
```

Once running, the MCP endpoint will be available at `http://localhost:8000/mcp` (or your custom network address/port).

### SSE Transport (Legacy)

Server-Sent Events transport for legacy web applications:

```bash
fastmcp run src/leantime_mcp/server.py:app --transport sse --port 8000
```

### Using FastMCP CLI

The FastMCP CLI provides additional options and better control:

```bash
# See all available options
fastmcp run --help

# Run with debug logging
fastmcp run src/leantime_mcp/server.py:app --transport http --log-level DEBUG
```

### Environment Variables

Set these environment variables for all transport types:

```bash
export LEANTIME_URL="https://your-leantime-instance.com"
export LEANTIME_API_KEY="your_api_key_here"
# Optional: email of the human operating the agent; used as the default
# assignee for tickets the bot creates (see "Identity model" above).
export LEANTIME_TARGET_USER_EMAIL="person-operating-the-agent@example.com"
# Optional: minimum acting-user role required for write/destructive tools
# (default 20 = editor). See "Write permissions" below.
export LEANTIME_WRITE_MIN_ROLE="20"
```

### Write permissions (read-only enforcement)

Leantime's JSON-RPC API does **not** enforce role-based write restrictions — an
authenticated key can write regardless of its user's role. To make
LLM-driven access read-only safely, this server gates every **write/destructive**
tool (`create_*`, `update_*`, `patch_ticket`, `set_ticket_status`,
`assign_ticket`, `delete_*`, `upsert_subtask`, `add_comment`, `edit_comment`,
`add_timesheet`, `create_milestone`) behind the acting user's Leantime role.
**Read tools are never gated.**

A write runs only if the acting user (the API key's owner, via whoami) has a
role `>=` `LEANTIME_WRITE_MIN_ROLE`; otherwise the tool returns a
`permission_denied` error without calling Leantime.

| Role | Value |
|------|-------|
| readonly | 5 |
| commenter | 10 |
| editor | 20 |
| manager | 30 |
| admin | 40 |
| owner | 50 |

- Default is `20` (editor): a `readonly` (5) or `commenter` (10) bot is
  effectively read-only.
- To make a deployment read-only, issue an API key owned by a low-role user and
  leave the default — no code change needed.
- To allow all writes regardless of role, set `LEANTIME_WRITE_MIN_ROLE=0`.

## Available Tools

The server provides the following MCP tools. Tools marked ✏️ perform **writes/deletes** and are gated by the acting user's Leantime role (`LEANTIME_WRITE_MIN_ROLE`, default `20`=editor — see [Write permissions](#write-permissions-read-only-enforcement)); all unmarked tools are read-only.

**Projects**
- `get_project` - Get details of a specific project
- `list_projects` - List all accessible projects
- `create_project` ✏️ - Create a new project
- `update_project` ✏️ - Update an existing project (only the fields you pass)
- `list_project_users` - List users assigned to a project

**Tickets**
- `get_ticket` - Get ticket/task details
- `list_tickets` - List tickets (optionally filtered by project)
- `list_my_tickets` - List a user's open tickets in a project
- `create_ticket` ✏️ - Create a new ticket
- `update_ticket` ✏️ - Update a ticket (full-save; blanks omitted fields)
- `patch_ticket` ✏️ - Partially update a ticket, changing ONLY the fields you pass (preferred)
- `set_ticket_status` ✏️ - Change only a ticket's status
- `assign_ticket` ✏️ - Assign a ticket to a user
- `delete_ticket` ✏️ - Delete a ticket
- `get_status_labels` - Map status IDs to labels
- `get_priority_labels` - Map priority IDs to labels
- `get_ticket_types` - List available ticket types

**Subtasks**
- `get_all_subtasks` - List a ticket's subtasks
- `upsert_subtask` ✏️ - Create or update a subtask

**Milestones**
- `list_milestones` - List a project's milestones
- `create_milestone` ✏️ - Create a milestone

**Comments**
- `add_comment` ✏️ - Add a comment to a ticket or project
- `get_comments` - Get comments for a module
- `edit_comment` ✏️ - Edit a comment's text
- `delete_comment` ✏️ - Delete a comment

**Timesheets**
- `add_timesheet` ✏️ - Log time to a ticket
- `get_timesheets` - Query timesheet entries
- `delete_timesheet` ✏️ - Delete a timesheet entry (no update RPC; delete + re-add)

**Users**
- `get_user` - Get user details
- `list_users` - List all users
- `get_current_user` - Get the acting user (the bot, via whoami from the API key)
- `get_target_user` - Get the configured human target (`LEANTIME_TARGET_USER_EMAIL`)
- `resolve_user` - Resolve an email address to a user (for per-call assignee targeting)


## Development

### Setup Development Environment

```bash
# Clone the repository
git clone https://github.com/AmariNoa/leantime-mcp.git
cd leantime-mcp

# Sync dependencies (includes dev dependencies)
uv sync

# Run from source
uv run leantime-mcp

# Run the tests
uv run --extra dev pytest
```

## Links

- [Leantime](https://leantime.io/)
- [Leantime API Documentation](https://docs.leantime.io/api/README)
- [Model Context Protocol](https://modelcontextprotocol.io/)
- [MCP Specification](https://spec.modelcontextprotocol.io/)

## Licensing

This project uses [REUSE](https://reuse.software/) for clear and comprehensive licensing information, following the [FSFE REUSE specification](https://reuse.software/spec/).

### License Information

All files contain SPDX license headers for clear identification. To check compliance:

```bash
uvx reuse lint
```