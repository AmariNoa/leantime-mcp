# SPDX-FileCopyrightText: 2025 Daniel Eder
# SPDX-FileCopyrightText: 2026 AmariNoa
#
# SPDX-License-Identifier: MIT
#
# Modified by AmariNoa: corrected the Comments RPC parameter names
# (entityId / values.text) so add_comment and get_comments match Leantime's
# JSON-RPC method signatures. Added whoami (Auth.getUserId) and per-process
# caches for the acting user and email->id lookups. Added dual authentication:
# a company API key (X-API-KEY, acts as the key's "bot" user) or a Personal
# Access Token (Authorization: Bearer, acts as the token's human owner). The
# PAT path requires the PersonalAccessTokenAuth plugin on the Leantime server.

"""Leantime JSON-RPC 2.0 client implementation."""

import httpx
from typing import Any, Optional
import logging

logger = logging.getLogger(__name__)


class LeantimeAPIError(Exception):
    """Exception raised for Leantime API errors."""
    
    def __init__(self, code: int, message: str, data: Any = None):
        self.code = code
        self.message = message
        self.data = data
        super().__init__(f"Leantime API Error {code}: {message}")


class LeantimeClient:
    """Client for interacting with Leantime's JSON-RPC 2.0 API."""
    
    def __init__(self, base_url: str, api_key: Optional[str] = None, pat: Optional[str] = None):
        """Initialize the Leantime client.

        Args:
            base_url: Base URL of the Leantime instance (e.g., https://leantime.example.com)
            api_key: Company API key, sent as X-API-KEY. Authenticates as the key's
                owner (typically a shared "bot" user). Used when no PAT is configured.
            pat: Personal Access Token, sent as Authorization: Bearer. Authenticates
                as the token's human owner (requires the PersonalAccessTokenAuth plugin
                on the server). Takes precedence over api_key when both are set.
        """
        if not api_key and not pat:
            raise ValueError("Either api_key or pat must be provided.")
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.pat = pat
        self.endpoint = f"{self.base_url}/api/jsonrpc"
        self._request_id = 0
        # Per-process caches. The acting user (the API key's owner) never
        # changes for the life of the process, and email->id mappings are
        # effectively immutable too, so we resolve each at most once.
        self._self_user_id: Optional[int] = None
        self._email_id_cache: dict[str, Optional[int]] = {}
    
    def _get_next_id(self) -> int:
        """Get next JSON-RPC request ID."""
        self._request_id += 1
        return self._request_id
    
    async def call(self, method: str, params: Optional[dict] = None) -> Any:
        """Make a JSON-RPC 2.0 call to Leantime API.
        
        Args:
            method: RPC method name (e.g., "leantime.rpc.Projects.getProject")
            params: Method parameters as dictionary
            
        Returns:
            The result from the JSON-RPC response
            
        Raises:
            LeantimeAPIError: If the API returns an error
            httpx.HTTPError: If there's a network/HTTP error
        """
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
            "id": self._get_next_id()
        }
        
        # PAT takes precedence: send ONLY the Bearer token so the server
        # authenticates as the token's human owner. Mixing X-API-KEY in would
        # let the api guard win and act as the bot instead.
        headers = {"Content-Type": "application/json"}
        if self.pat:
            headers["Authorization"] = f"Bearer {self.pat}"
        else:
            headers["X-API-KEY"] = self.api_key

        logger.debug(f"Calling Leantime RPC: {method} with params: {params}")
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.endpoint,
                json=payload,
                headers=headers,
                timeout=30.0
            )
            response.raise_for_status()
            
            data = response.json()
            
            # Check for JSON-RPC error
            if "error" in data:
                error = data["error"]
                raise LeantimeAPIError(
                    code=error.get("code", -1),
                    message=error.get("message", "Unknown error"),
                    data=error.get("data")
                )
            
            # Return the result
            return data.get("result")
    
    # Convenience methods for common operations
    
    async def get_project(self, project_id: int) -> dict:
        """Get project details by ID."""
        return await self.call("leantime.rpc.Projects.getProject", {"id": project_id})
    
    async def list_projects(self) -> list:
        """List all projects."""
        return await self.call("leantime.rpc.Projects.getAll")
    
    async def create_project(self, name: str, details: Optional[str] = None, **kwargs) -> dict:
        """Create a new project.

        Leantime's ``leantime.rpc.Projects.addProject(array $values)`` expects a
        single ``values`` param holding the project columns (matching the
        ``editProject``/``addTicket`` convention). Sending the columns at the top
        level makes the API return -32602 Invalid params, so we wrap them here.
        Unset optional kwargs (e.g. ``clientId=None``) are dropped so we never
        send nulls for fields Leantime treats as required.
        """
        values = {"name": name}
        if details is not None:
            values["details"] = details
        for key, value in kwargs.items():
            if value is not None:
                values[key] = value
        return await self.call("leantime.rpc.Projects.addProject", {"values": values})

    async def update_project(self, project_id: int, fields: dict) -> Any:
        """Update an existing project with the given fields.

        Args:
            project_id: The ID of the project to update
            fields: Mapping of project columns to new values (name, details,
                clientId, state, etc.)
        """
        values = {"id": project_id, **fields}
        return await self.call(
            "leantime.rpc.Projects.editProject", {"values": values, "id": project_id}
        )

    async def list_project_users(self, project_id: int) -> list:
        """List users assigned to a project."""
        return await self.call(
            "leantime.rpc.Projects.getUsersAssignedToProject", {"projectId": project_id}
        )

    # --- Clients -------------------------------------------------------------

    async def list_clients(self) -> list:
        """List all clients (id, name, website, project count)."""
        return await self.call("leantime.rpc.Clients.Clients.getAll")

    async def get_client(self, client_id: int) -> dict:
        """Get a single client's full details by ID."""
        return await self.call(
            "leantime.rpc.Clients.Clients.get", {"id": client_id}
        )

    async def create_client(self, name: str, **fields) -> Any:
        """Create a new client and return its new id.

        Maps to Leantime's ``Clients.create(array $values)`` (the validating
        ``createClient`` wrapper is not exposed over JSON-RPC on this server, so
        ``name`` is enforced at the tool layer instead). ``name`` is required;
        recognised optional columns are street, zip, city, state, country,
        phone, internet (website) and email. Unset (None) fields are dropped so
        Leantime applies its own empty-string defaults.
        """
        values = {"name": name}
        for key, value in fields.items():
            if value is not None:
                values[key] = value
        return await self.call(
            "leantime.rpc.Clients.Clients.create", {"values": values}
        )

    async def update_client(self, client_id: int, fields: dict) -> Any:
        """Partially update a client, changing ONLY the fields you pass.

        Leantime's ``Clients.editClient`` re-saves the whole client row and
        blanks any column missing from ``values`` (there is no per-field patch
        for clients). To get safe partial-update semantics we read the current
        client, overlay the supplied fields, and send the merged record back.
        """
        current = await self.get_client(client_id)
        if not isinstance(current, dict) or not current:
            raise LeantimeAPIError(-32602, f"Client {client_id} not found")
        # numberOfProjects is a computed read-only field; never write it back.
        merged = {k: v for k, v in current.items() if k != "numberOfProjects"}
        for key, value in fields.items():
            if value is not None:
                merged[key] = value
        merged["id"] = client_id
        return await self.call(
            "leantime.rpc.Clients.Clients.editClient", {"values": merged}
        )

    async def delete_client(self, client_id: int) -> Any:
        """Delete a client by ID.

        WARNING: Leantime's ``Clients.delete`` also deletes every project (and
        their tickets) belonging to the client. This is irreversible.
        """
        return await self.call(
            "leantime.rpc.Clients.Clients.delete", {"id": client_id}
        )
    
    async def get_ticket(self, ticket_id: int) -> dict:
        """Get ticket details by ID."""
        return await self.call("leantime.rpc.Tickets.Tickets.getTicket", {"id": ticket_id})
    
    async def list_tickets(self, project_id: Optional[int] = None) -> list:
        """List tickets, optionally filtered by project."""
        searchCriteria = {}
        if project_id:
            searchCriteria["currentProject"] = project_id
        params = {"searchCriteria": searchCriteria}
        return await self.call("leantime.rpc.Tickets.Tickets.getAll", params)
    
    async def create_ticket(self, headline: str, project_id: int, user_id: int, date: Optional[str] = None, tags: Optional[str] = None, **kwargs) -> dict:
        """Create a new ticket.
        
        Args:
            headline: Title/headline of the ticket
            project_id: Project ID where the ticket will be created
            user_id: The ID of the user creating the ticket
            date: The date when the ticket is created (YYYY-MM-DD format). Defaults to current date if not provided.
            tags: Comma-separated list of tags to add to the ticket
            **kwargs: Additional parameters
        """
        from datetime import datetime
        
        # Use current date if none provided
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        
        # The API expects a 'values' parameter containing the ticket data
        values = {
            "headline": headline, 
            "projectId": project_id,
            "userId": user_id,
            "date": date,
            **kwargs
        }
        
        # Add tags if provided
        if tags is not None:
            values["tags"] = tags
        
        params = {"values": values}
        return await self.call("leantime.rpc.Tickets.Tickets.addTicket", params)
    
    async def update_ticket(self, ticket_id: int, project_id: int, **kwargs) -> dict:
        """Update an existing ticket.

        Args:
            ticket_id: The ID of the ticket to update
            project_id: The project ID where the ticket belongs
            **kwargs: Additional parameters to update
        """
        values = {"id": ticket_id, "projectId": project_id, **kwargs}
        params = {"values": values}
        return await self.call("leantime.rpc.Tickets.Tickets.updateTicket", params)

    async def patch_ticket(self, ticket_id: int, fields: dict) -> Any:
        """Partially update a ticket, changing ONLY the given fields.

        Unlike update_ticket (which re-saves the whole ticket and blanks any
        field that is not supplied), this maps to Leantime's Tickets.patch,
        which updates exactly the keys in ``fields`` and leaves the rest intact.

        Args:
            ticket_id: The ID of the ticket to patch
            fields: Mapping of Leantime ticket columns to new values, e.g.
                {"status": 3}, {"editorId": 7}, {"headline": "..."},
                {"milestoneid": 12}, {"dateToFinish": "2026-06-30"}.
        """
        return await self.call(
            "leantime.rpc.Tickets.Tickets.patch",
            {"id": ticket_id, "params": fields},
        )

    async def delete_ticket(self, ticket_id: int) -> Any:
        """Delete a ticket by ID."""
        return await self.call("leantime.rpc.Tickets.Tickets.delete", {"id": ticket_id})

    async def get_open_user_tickets(self, user_id: int, project_id: int) -> list:
        """Get a user's open (not-done) tickets in a project."""
        return await self.call(
            "leantime.rpc.Tickets.Tickets.getOpenUserTicketsByProject",
            {"userId": user_id, "projectId": project_id},
        )

    async def list_milestones(self, project_id: int) -> list:
        """List milestones for a project."""
        return await self.call(
            "leantime.rpc.Tickets.Tickets.getAllMilestones",
            {"searchCriteria": {"currentProject": project_id}},
        )

    async def create_milestone(self, headline: str, project_id: int, user_id: int,
                               date: Optional[str] = None, **kwargs) -> Any:
        """Create a milestone.

        Leantime has no dedicated addMilestone RPC; milestones are tickets of
        type "milestone", so this routes through addTicket with type set.

        Args:
            headline: Milestone title
            project_id: Project the milestone belongs to
            user_id: Author user ID
            date: Creation date (YYYY-MM-DD). Defaults to today.
            **kwargs: Extra ticket fields (editFrom, editTo, tags, description,
                headline color, etc.)
        """
        from datetime import datetime
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        values = {
            "headline": headline,
            "type": "milestone",
            "projectId": project_id,
            "userId": user_id,
            "date": date,
            **kwargs,
        }
        return await self.call(
            "leantime.rpc.Tickets.Tickets.addTicket", {"values": values}
        )

    async def get_ticket_types(self) -> Any:
        """Get available ticket types (task, story, bug, etc.)."""
        return await self.call("leantime.rpc.Tickets.Tickets.getTicketTypes")

    async def get_priority_labels(self) -> Any:
        """Get available priority IDs mapped to their labels."""
        return await self.call("leantime.rpc.Tickets.Tickets.getPriorityLabels")
    
    async def get_status_labels(self) -> dict:
        """Get all available ticket status labels with their IDs.
        
        Returns:
            A dictionary mapping status IDs to their labels
        """
        return await self.call("leantime.rpc.Tickets.Tickets.getStatusLabels")
    
    async def get_user(self, user_id: int) -> dict:
        """Get user details by ID."""
        return await self.call("leantime.rpc.Users.getUser", {"id": user_id})
    
    async def list_users(self) -> list:
        """List all users."""
        return await self.call("leantime.rpc.Users.getAll")
    
    async def get_user_by_email(self, email: str) -> dict:
        """Get user details by email address."""
        return await self.call("leantime.rpc.Users.Users.getUserByEmail", {"email": email})

    async def whoami(self) -> int:
        """Return the acting user's ID (the user that owns the API key).

        Resolved server-side from the API key via Auth.getUserId, so no user
        ID or email needs to be configured. Cached for the life of the client
        (the key's owner does not change).
        """
        if self._self_user_id is None:
            result = await self.call("leantime.rpc.Auth.getUserId")
            self._self_user_id = int(result)
        return self._self_user_id

    async def resolve_email_to_id(self, email: str) -> Optional[int]:
        """Resolve an email address to a user ID, cached per process.

        Returns None if the email does not map to a user.
        """
        if email not in self._email_id_cache:
            user = await self.get_user_by_email(email)
            self._email_id_cache[email] = (
                user.get("id") if isinstance(user, dict) else None
            )
        return self._email_id_cache[email]
    
    async def add_comment(self, module: str, module_id: int, comment: str) -> dict:
        """Add a comment to a module (e.g., ticket, project)."""
        # Leantime's Comments.addComment signature is
        # addComment($values, $module, $entityId, $entity = null); the comment
        # text is passed inside the $values array as "text", and the entity id
        # parameter is named "entityId" (not "moduleId").
        params = {
            "values": {"text": comment},
            "module": module,
            "entityId": module_id
        }
        return await self.call("leantime.rpc.Comments.addComment", params)

    async def get_comments(self, module: str, module_id: int) -> list:
        """Get comments for a module."""
        # Leantime's Comments.getComments expects the entity id parameter to be
        # named "entityId" (not "moduleId").
        params = {
            "module": module,
            "entityId": module_id
        }
        return await self.call("leantime.rpc.Comments.getComments", params)

    async def edit_comment(self, comment_id: int, comment: str) -> Any:
        """Edit the text of an existing comment.

        Mirrors add_comment's convention: the text is passed inside a
        ``values`` array as "text".
        """
        params = {"values": {"text": comment}, "id": comment_id}
        return await self.call("leantime.rpc.Comments.editComment", params)

    async def delete_comment(self, comment_id: int) -> Any:
        """Delete a comment by ID."""
        # Leantime's Comments.deleteComment expects the parameter named
        # "commentId" (not "id").
        return await self.call(
            "leantime.rpc.Comments.deleteComment", {"commentId": comment_id}
        )
    
    async def add_timesheet(self, user_id: int, ticket_id: int, hours: float, date: str, **kwargs) -> dict:
        """Add a timesheet entry."""
        params = {
            "userId": user_id,
            "ticketId": ticket_id,
            "hours": hours,
            "date": date,
            **kwargs
        }
        return await self.call("leantime.rpc.Timesheets.addTime", params)
    
    async def get_timesheets(self, project_id: Optional[int] = None, user_id: Optional[int] = None) -> list:
        """Get timesheet entries."""
        params = {}
        if project_id:
            params["projectId"] = project_id
        if user_id:
            params["userId"] = user_id
        return await self.call("leantime.rpc.Timesheets.getTimesheets", params)

    async def delete_timesheet(self, timesheet_id: int) -> Any:
        """Delete a timesheet entry by ID.

        Note: Leantime exposes no updateTime RPC; to correct an entry, delete
        it and add a new one.
        """
        return await self.call("leantime.rpc.Timesheets.deleteTime", {"id": timesheet_id})
    
    async def get_all_subtasks(self, ticket_id: int) -> list:
        """Get all subtasks for a ticket.
        
        Args:
            ticket_id: The ID of the parent ticket
            
        Returns:
            A list of subtasks or false if an error occurred
        """
        params = {"ticketId": ticket_id}
        return await self.call("leantime.rpc.Tickets.Tickets.getAllSubtasks", params)
    
    async def upsert_subtask(self, parent_ticket_id: int, headline: str, date: Optional[str] = None, tags: Optional[str] = None, **kwargs) -> dict:
        """Create or update a subtask.
        
        Args:
            parent_ticket_id: The ID of the parent ticket
            headline: Title/headline of the subtask
            date: The date when the subtask is created (YYYY-MM-DD format). Defaults to current date if not provided.
            tags: Comma-separated list of tags to add to the subtask
            **kwargs: Additional parameters (description, status, priority, assignedTo, etc.)
            
        Returns:
            The created subtask data
        """
        from datetime import datetime
        
        # Use current date if none provided
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        
        # Fetch the parent ticket data to get project_id and milestone_id
        parent_ticket_data = await self.get_ticket(parent_ticket_id)
        
        if not parent_ticket_data:
            raise ValueError(f"Parent ticket with ID {parent_ticket_id} not found")
        
        # Extract required fields from parent ticket
        project_id = parent_ticket_data.get("projectId")
        if not project_id:
            raise ValueError(f"Could not determine projectId from parent ticket {parent_ticket_id}")
        
              # Extract required fields from parent ticket
        user_id = parent_ticket_data.get("userId")
        if not user_id:
            raise ValueError(f"Could not determine userId from parent ticket {parent_ticket_id}")

        milestone_id = parent_ticket_data.get("milestoneid")
        
        # The API expects a 'values' parameter containing the subtask data
        values = {
            "headline": headline,
            "type": "subtask",  # Mark this as a subtask
            "projectId": project_id,
            "userId": user_id,
            "date": date,
            "dependingTicketId": parent_ticket_id,  # Link to parent ticket
            "milestoneid": milestone_id if milestone_id else "",  # Use parent's milestone
            **kwargs
        }
        
        # Add tags if provided
        if tags is not None:
            values["tags"] = tags
        
        # Use addTicket to create the subtask
        params = {"values": values}
        
        # Debug logging
        logger.info(f"Creating subtask via addTicket: type=subtask, dependingTicketId={parent_ticket_id}, milestoneid={milestone_id}")
        
        return await self.call("leantime.rpc.Tickets.Tickets.addTicket", params)
