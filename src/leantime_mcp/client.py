# SPDX-FileCopyrightText: 2025 Daniel Eder
#
# SPDX-License-Identifier: MIT

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
    
    def __init__(self, base_url: str, api_key: str):
        """Initialize the Leantime client.
        
        Args:
            base_url: Base URL of the Leantime instance (e.g., https://leantime.example.com)
            api_key: API key for authentication
        """
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.endpoint = f"{self.base_url}/api/jsonrpc"
        self._request_id = 0
    
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
        
        headers = {
            "Content-Type": "application/json",
            "X-API-KEY": self.api_key
        }
        
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
        """Create a new project."""
        params = {"name": name, **kwargs}
        if details:
            params["details"] = details
        return await self.call("leantime.rpc.Projects.addProject", params)
    
    async def get_ticket(self, ticket_id: int) -> dict:
        """Get ticket details by ID."""
        return await self.call("leantime.rpc.Tickets.Tickets.getTicket", {"id": ticket_id})
    
    async def list_tickets(self, project_id: Optional[int] = None) -> list:
        """List tickets, optionally filtered by project."""
        params = {}
        if project_id:
            params["searchCriteria"] = {"projectId": project_id}
        return await self.call("leantime.rpc.Tickets.Tickets.getAll", params)
    
    async def create_ticket(self, headline: str, project_id: int, user_id: int, date: Optional[str] = None, **kwargs) -> dict:
        """Create a new ticket.
        
        Args:
            headline: Title/headline of the ticket
            project_id: Project ID where the ticket will be created
            user_id: The ID of the user creating the ticket
            date: The date when the ticket is created (YYYY-MM-DD format). Defaults to current date if not provided.
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
        
        params = {"values": values}
        return await self.call("leantime.rpc.Tickets.Tickets.addTicket", params)
    
    async def update_ticket(self, ticket_id: int, **kwargs) -> dict:
        """Update an existing ticket."""
        values = {"id": ticket_id, **kwargs}
        params = {"values": values}
        return await self.call("leantime.rpc.Tickets.Tickets.updateTicket", params)
    
    async def get_user(self, user_id: int) -> dict:
        """Get user details by ID."""
        return await self.call("leantime.rpc.Users.getUser", {"id": user_id})
    
    async def list_users(self) -> list:
        """List all users."""
        return await self.call("leantime.rpc.Users.getAll")
    
    async def get_user_by_email(self, email: str) -> dict:
        """Get user details by email address."""
        return await self.call("leantime.rpc.Users.Users.getUserByEmail", {"email": email})
    
    async def add_comment(self, module: str, module_id: int, comment: str) -> dict:
        """Add a comment to a module (e.g., ticket, project)."""
        params = {
            "module": module,
            "moduleId": module_id,
            "comment": comment
        }
        return await self.call("leantime.rpc.Comments.addComment", params)
    
    async def get_comments(self, module: str, module_id: int) -> list:
        """Get comments for a module."""
        params = {
            "module": module,
            "moduleId": module_id
        }
        return await self.call("leantime.rpc.Comments.getComments", params)
    
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
