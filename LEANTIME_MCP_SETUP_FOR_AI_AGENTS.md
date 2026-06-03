<!--
SPDX-FileCopyrightText: 2026 AmariNoa
SPDX-License-Identifier: MIT
-->

# Leantime MCP — Setup guide for AI agents

> **Audience: any AI agent** (Claude Code, Codex, Cursor, LM Studio, or any
> other MCP-capable host). Read this top to bottom and add the `leantime` MCP
> server to your host's configuration. Ask the human only for the inputs marked
> **[ASK HUMAN]**. **Identify yourself** for the agent name — see §1.
>
> The goal is a personal, per-user connection where you operate the Leantime API
> **as the human** via a Personal Access Token (PAT).
>
> This document is intentionally instance-agnostic: it contains **no real URLs
> or secrets**. The instance URL and the token are supplied by the human at
> setup time and live only in the local MCP config (never committed).

---

## 0. Concepts (read first)

This MCP talks to a Leantime instance over its JSON-RPC API. There are two
authentication modes — pick **PAT** for a personal agent:

| Mode | Env var | Acts as | Use when |
|------|---------|---------|----------|
| **PAT (recommended for a personal agent)** | `LEANTIME_PAT` | the token's **human owner** | a personal agent acting as one human |
| API key | `LEANTIME_API_KEY` | a shared **bot** user | shared / headless deployments |

Rules the client follows:
- If `LEANTIME_PAT` is set, the agent authenticates as **Bearer** and acts as
  the human who owns the token. `LEANTIME_API_KEY` is then ignored.
- Otherwise it uses `LEANTIME_API_KEY` (the bot).
- `LEANTIME_AGENT_NAME` appends a `Co-Authored-By: <name>` trailer to comments
  so it's clear which AI produced them. It works in both modes.

**Never commit the PAT/API key or the instance URL.** They live only in the
local MCP config.

---

## 1. Inputs to collect

- **[ASK HUMAN]** `LEANTIME_URL` — the base URL of the Leantime instance
  (e.g. `https://leantime.example.com`, no trailing slash).
- **[ASK HUMAN]** `LEANTIME_PAT` — a Personal Access Token for the human's own
  account. If they don't have one, walk them through **§2**.
- `LEANTIME_AGENT_NAME` — **your own name. Identify yourself**: set this to the
  name of the AI agent/product you are (for example `Claude Code`, `Codex`,
  `Cursor`, `LM Studio`, …). If you cannot determine your own product name with
  confidence, **[ASK HUMAN]** what to call you.

In the snippets below, substitute:
- `<LEANTIME_URL>` and `<PAT>` — the values the human gives you.
- `<YOUR_AGENT_NAME>` — your own name (see above).

Prerequisites on the machine: `uv` (which provides `uvx`) installed and on PATH
(https://github.com/astral-sh/uv).

---

## 2. [ASK HUMAN] Create a Personal Access Token (one-time, in the browser)

The human does this once and pastes the token back to you:

1. Sign in to the Leantime instance (`<LEANTIME_URL>`).
2. Open **Account Settings** (your profile) → the **Personal Access Tokens** tab.
3. Enter a **Label** (required, unique per user — e.g. include the agent name and
   machine) and an expiry in **days** (default 90), then **Create token**.
4. A dialog shows the token **once** — copy it now (it cannot be retrieved later).
5. Paste it to the agent as `LEANTIME_PAT`.

> Admins can also issue/revoke tokens for any user from **Company → Administration
> → Access Tokens**, or via CLI on the server:
> `php bin/leantime pat:create <userId> "<label>" --days=90`.

---

## 3. Add the `leantime` MCP server (initial setup)

The server definition is the same for every host — only where you put it differs.

**Canonical MCP server definition** (substitute the three placeholders):

```json
{
  "mcpServers": {
    "leantime": {
      "type": "stdio",
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/AmariNoa/leantime-mcp.git",
        "leantime-mcp"
      ],
      "env": {
        "LEANTIME_URL": "<LEANTIME_URL>",
        "LEANTIME_PAT": "<PAT>",
        "LEANTIME_AGENT_NAME": "<YOUR_AGENT_NAME>"
      }
    }
  }
}
```

**Where to put it (pick your host):**
- **Claude Code** — run, or merge into `~/.claude.json` under `mcpServers`:
  ```bash
  claude mcp add leantime --scope user \
    --env LEANTIME_URL=<LEANTIME_URL> \
    --env LEANTIME_PAT=<PAT> \
    --env LEANTIME_AGENT_NAME=<YOUR_AGENT_NAME> \
    -- uvx --from git+https://github.com/AmariNoa/leantime-mcp.git leantime-mcp
  ```
- **LM Studio** — `~/.lmstudio/mcp.json` (same `mcpServers` shape).
- **Codex / other MCP hosts** — add the server to that host's MCP config in its
  documented location, using the same `command`/`args`/`env`.

Then reload / reconnect MCP servers. The first launch fetches the server via
`uvx`; if a stale version is cached, add `--refresh` right after `uvx`.

---

## 4. Migration (replace an existing API-key config with a PAT)

If a `leantime` (or similarly named) MCP entry already exists using
`LEANTIME_API_KEY`, switch it to act as the human:

1. Locate the entry in your host's MCP config.
2. In its `env`:
   - **Remove** `LEANTIME_API_KEY` (and any stale `LEANTIME_USER_EMAIL` /
     `LEANTIME_TARGET_USER_EMAIL` — not needed in PAT mode).
   - **Add** `LEANTIME_PAT` = the human's token (from §2).
   - **Add** `LEANTIME_AGENT_NAME` = `<YOUR_AGENT_NAME>`.
   - Keep `LEANTIME_URL`.
3. Leave `command`/`args` as-is (`uvx --from git+…leantime-mcp`).
4. Reload / reconnect.

> If both `LEANTIME_PAT` and `LEANTIME_API_KEY` are present, the PAT wins (acts
> as the human). To fully switch identity, removing the API key is cleanest.

Resulting `env`:

```json
"env": {
  "LEANTIME_URL": "<LEANTIME_URL>",
  "LEANTIME_PAT": "<PAT>",
  "LEANTIME_AGENT_NAME": "<YOUR_AGENT_NAME>"
}
```

---

## 5. Verify

After reconnecting, confirm you are acting as the human:

1. Call the MCP tool **`get_current_user`** → it should return **the human's own
   user** (name/email), **not** the shared API-key bot.
2. Optional: create a test comment on a ticket via **`add_comment`**, then check
   it in the Leantime UI — it should be authored by the human and end with
   `Co-Authored-By: <YOUR_AGENT_NAME>`. Delete the test comment afterward.

If `get_current_user` still shows the bot, the PAT isn't being used: re-check
that `LEANTIME_PAT` is set (and `LEANTIME_API_KEY` removed) and that the MCP was
reloaded.

---

## 6. Maintenance

- **Rotation/expiry**: PATs can expire (default 90 days). When one expires,
  create a new one (§2) and update `LEANTIME_PAT`. Revoke old tokens from the
  Personal Access Tokens tab.
- **Security**: the PAT grants the human's full account access — keep it (and the
  instance URL) only in the local MCP config, never in git or chat logs. HTTPS
  only.
- **Server requirement**: PAT (Bearer) auth requires the
  `PersonalAccessTokenAuth` plugin to be installed/enabled on the Leantime
  server (a fresh server would need it).
