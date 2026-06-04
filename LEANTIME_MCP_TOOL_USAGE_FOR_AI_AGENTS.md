<!--
SPDX-FileCopyrightText: 2026 AmariNoa
SPDX-License-Identifier: MIT
-->

# Leantime MCP — Tool call conventions for AI agents

> **Audience: any AI agent** that calls the `leantime` MCP tools (Claude Code,
> Codex, Cursor, **LM Studio**, or any other MCP host). This is a companion to
> `LEANTIME_MCP_SETUP_FOR_AI_AGENTS.md` (which covers *connecting*); this file
> covers *how to call the tools correctly* — the parameter-passing rules that are
> not obvious from the JSON schema alone.
>
> **How to use this file:** the same rules are baked into each tool's
> `description` (the MCP host shows them to you automatically). Smaller local
> models sometimes skim those, so you may also paste the relevant parts of this
> file into the host's **system prompt** as reinforcement. It is intentionally
> instance-agnostic — no real URLs, ids, or secrets. Discover concrete ids at
> call time with the `list_*` / `get_*` tools.

---

## 0. General principles

1. **Discover ids before you write.** Most write tools need numeric ids (project,
   client, user, status, priority). Don't guess them — fetch them first:
   - projects → `list_projects`   · clients → `list_clients`   · users → `list_users` / `resolve_user(email)`
   - status ids → `get_status_labels`   · priority ids → `get_priority_labels`   · ticket types → `get_ticket_types`
2. **Writes are role-gated.** Create/update/delete/assign tools are refused for
   read-only roles and return an error object instead of acting. A returned
   `{"error": ...}` is a normal result — read it, don't retry blindly.
3. **Rate limit.** The Leantime API returns **HTTP 429** under bursts. Make write
   calls sequentially; if you get a 429, back off briefly and retry once — do not
   hammer it in a loop.
4. **Schema-optional ≠ truly optional.** Some parameters are optional in the
   schema but required in practice (see §1). Read the tool description, not just
   the `required` array.
5. **Partial vs full payloads.** For update/assign tools, pass **only what you
   want to change / add** — these tools merge internally. Never reconstruct and
   resend the whole prior list/record (see §2).

---

## 1. "Optional in schema, required in practice"

| Tool | Watch out for |
|------|---------------|
| `create_project` | `clientId` is optional in the signature but **effectively required** — omitting it fails with a `-32000` server error. Always pass a valid client id (find one via `list_clients`). Only `name`, `details`, `clientId` are accepted; set anything else with `update_project` afterward. |
| `create_ticket` | `headline` + `project_id` are required. Author (`user_id`) defaults to the acting account — normally omit it. Assignee precedence: `assignee_email` → `assignedTo` (id) → configured target user → none. Prefer `assignee_email` so you don't need to resolve the id yourself. |
| `create_client` | Only `name` is required, but Leantime **rejects an empty or duplicate name**. `internet` means the website URL. |

---

## 2. Internal-merge tools — pass partial input, NOT the whole list

These tools read the current state and merge your change in. Passing a full
list/record is unnecessary and, for assignments, **actively wrong**.

| Tool | Correct usage |
|------|---------------|
| `assign_user_to_project` | Call once per **(user_id, project_id)** pair with a **single** project id. **Do NOT pass a list of project ids.** The tool reads the user's current project set and adds this one, preserving all others. Idempotent (re-running is a no-op). To add a user to N projects, make N calls. |
| `update_client` | Pass **only the fields you want to change**. Unspecified fields are preserved (the tool reads the current client and merges). Sending blanks for fields you didn't intend to change would erase them — so just omit them. |
| `update_ticket` | Pass `ticket_id` + `project_id` plus **only the fields you are changing**. |

> Mental model: for these tools you describe the *delta*, not the *desired full
> state*. The server-side union/merge is the tool's job, not yours.

---

## 3. Destructive / irreversible tools — confirm the id first

| Tool | Why it's dangerous |
|------|--------------------|
| `delete_client` | **Cascades**: deleting a client also deletes **ALL of its projects and their tickets**. Irreversible. Re-read the client with `get_client` and confirm with the human before calling. |
| `delete_ticket` | Removes the ticket (and its subtasks). Irreversible. |
| `delete_comment` | Irreversible. |
| `delete_timesheet` | Leantime has no timesheet *update*; the pattern is delete + re-add. |

When in doubt about a delete, **read the target first** (`get_*`) and surface
what you found to the human rather than proceeding.

---

## 4. Identity & assignee helpers

- `get_current_user` — the account you are acting as (the PAT's human owner, or
  the API-key bot). Use to confirm identity after setup.
- `get_target_user` — the configured default human assignee
  (`LEANTIME_TARGET_USER_EMAIL`), if set.
- `resolve_user(email)` — email → user id (case-insensitive; returns an error
  object for unknown emails). Use this to turn a name/email into an id before an
  assignment or `assignedTo`.

---

## 5. Quick recipe — add a member to a project

1. `list_projects` → find the target `project_id`.
2. `list_users` (or `resolve_user(email)`) → find the `user_id`.
3. `list_project_users(project_id)` → check they're not already a member.
4. `assign_user_to_project(user_id, project_id)` → single ids, no lists.
5. `list_project_users(project_id)` → confirm they now appear.
