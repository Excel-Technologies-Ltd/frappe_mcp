# Frappe MCP

Universal [Model Context Protocol](https://modelcontextprotocol.io) server for any Frappe site. Each person gets one connector. The tools answer as that Frappe user, so user permissions, user permissions (restrictions), and if-owner rules still apply.

Works with Frappe alone or with ERPNext, HRMS, and custom apps. DocTypes are discovered from the live site. Nothing is hardcoded to one product.

Transport is stateless streamable HTTP. Clients POST one JSON-RPC object to the server URL. Batch arrays are rejected. Supported protocol versions: `2025-06-18`, `2025-03-26`, `2024-11-05`.

## Install

```bash
bench get-app <path-or-url-to-frappe_mcp>
bench --site <site> install-app frappe_mcp
bench --site <site> migrate
bench build --app frappe_mcp
```

Requires Python 3.10+ and Frappe v14. The only extra Python dependency is `qdrant-client`. Semantic search does nothing until Qdrant and an embedding model are configured.

Install creates the **MCP User** role and a single **MCP Settings** document. Give **MCP User** to people who should own a connector. System Managers and Administrator can create a connector for any user. Data access still comes from the user's normal roles (Sales User, HR User, and so on), not from MCP User.

After migrate, open the **Frappe MCP** workspace.

## One connector per user

A user can have only one **MCP Connector**. The name is a series, for example `MCP-2026-00001` (`MCP-.YYYY.-.#####`, or `MCP-CONN-.YYYY.-.#####`).

The list shows, in order: ID, User Full Name, User Email, Status, Connector Name, Last Used. Status is the Enabled check.

**Connector Name** is required. Full name and email are copied from the user.

System Manager and Administrator get three list menu items:

- **Bulk Create** — pick a Role (searchable), type one Connector Name, then either check **All matching users** or tick users. Users who already have a connector are skipped. The same Connector Name is written on every new row.
- **Export Connectors** — CSV of connector metadata. Raw keys are not included.
- **Regenerate & Export** — replaces keys and downloads them once.

Optional on each connector: expiry date, requests per minute (`0` means unlimited), an IP or CIDR allow list, and a DocType allow list or block list. A blank allow list means every DocType that user can already open.

## What a connector can do

| Action | Default |
| --- | --- |
| Read | On |
| Create | On |
| Update | On |
| Submit | Off |
| Cancel | Off |
| Delete | Off |

**MCP Settings** is the ceiling. A connector can turn a write off. It can turn Submit, Cancel, or Delete on only when the site setting is already on. Frappe permissions are a second gate inside every tool.

Password fields are masked. User, Role, and this app's own connector, log, and chat DocTypes are not exposed as data tools.

Writes are confirm-gated. The first call (`confirm` false or omitted) previews. The second call, with `confirm: true`, performs the change only after the person explicitly agrees. Each tool call runs inside the `mcp_tool_call` savepoint.

## Connect a client

Open **Frappe MCP → Connect** (`/app/mcp-connect`) while you are on the public https address, then copy the server URL. The box masks the key. Copy pastes the real link.

```text
https://<public-host>/mcp/<key>/message
```

The key is the path segment, same shape as a Zoho MCP URL. No header is required. These paths all accept the key:

- `POST /mcp/<key>/message`
- `POST /mcp/<key>`
- `POST /mcp` with a header (below)

Regenerate API Key on that page, or **Regenerate Token** on the connector, replaces the key immediately. The previous URL and header stop working. One dialog shows the new server URL, the token, and the client config.

The raw key is also stored encrypted so Connect can show the URL again. Lookup still uses the SHA-256 hash. A connector created before that field existed has no stored key until you regenerate.

### Header clients (Cursor, Claude)

```json
{
  "mcpServers": {
    "frappe": {
      "url": "https://<public-host>/mcp",
      "headers": {
        "Authorization": "Bearer fmcp_...",
        "x-api-key": "fmcp_..."
      }
    }
  }
}
```

Header order on the server is `X-Api-Key`, `X-Auth-Token`, `X-Frappe-MCP-Token`, then `Authorization`. A value may include a `Bearer ` prefix. Claude custom connectors only allow approved header names: pick `x-api-key` from Claude's list, paste the raw token, leave sign-in off, and use streamable HTTP. `Authorization: Bearer <token>` still works for Cursor. The token authenticates only `/mcp` and `/mcp/...`. It does not log the user into the desk.

### ChatGPT and Gemini (OAuth)

Both require standard OAuth on `https://<public-host>/mcp`. The first time someone clicks Allow, a connector is created for that Frappe user if they do not already have one. The OAuth access token points at that connector. It does not replace the connector key used by Cursor or Claude.

1. Publish the site over https. On a free ngrok address, open the public URL once in a browser and pass the warning page. Sign-in during the chat app's redirect must happen on that public host, not `localhost`, so the session cookie matches.
2. ChatGPT: add a custom MCP server, leave Authentication on OAuth, and continue. Log in as the Frappe user and choose Allow.
3. Gemini: use the same server URL. Gemini registers itself. If it asks for a client id and secret, open **MCP Settings**, click **OAuth Client**, and paste those two values.

Discovery:

| URL | Purpose |
| --- | --- |
| `GET /.well-known/oauth-protected-resource` | Resource metadata |
| `GET /.well-known/oauth-protected-resource/mcp` | Same, linked from the 401 `WWW-Authenticate` header |
| `GET /.well-known/oauth-authorization-server` | Authorization server metadata |
| `GET /.well-known/openid-configuration` | Same document, for clients that look there |
| `POST /register` and `POST /oauth/register` | Dynamic client registration |
| `GET/POST /oauth/authorize` | Login, then Allow or Deny |
| `POST /oauth/token` | Authorization code and refresh token |

The metadata advertises PKCE `S256`, `authorization_code`, `refresh_token`, and token auth methods `client_secret_post`, `client_secret_basic`, and `none`. Public clients must send PKCE. Confidential clients may use a client secret; if they also send a challenge, it is checked. Every redirect back to the chat app includes `state` and `iss`. Access tokens last one hour. Refresh tokens last 30 days and rotate. Redirect URIs must be https, or http on localhost. A dynamically registered client may only use the redirect URIs it registered. The default client may use any https redirect.

## Tools

- `whoami`, `list_doctypes`, `get_schema`, `get_permissions`
- `get_record`, `get_child_records`, `get_comments`, `get_attachments`, `get_linked_documents`
- `count_records`, `query_records`, `aggregate_field`, `search_link`, `resolve_date_range`
- `list_reports`, `run_report` (Query Report and Script Report, when **Enable Reports Tool** is on)
- `semantic_search_records`, `semantic_search_doctypes` (when semantic search is fully configured)
- `create_record`, `update_record`, `add_comment`
- `get_workflow`, `apply_workflow_action`
- `submit_document`, `cancel_document`, `delete_document` (only when allowed)

`GET /mcp` returns server name, version, and transport. Resources and prompts are on the same endpoint. `DELETE /mcp` returns 200. An unauthenticated POST returns JSON-RPC `-32001` and a `WWW-Authenticate` header that points clients at the OAuth metadata.

Queries go through `frappe.get_list`. Field names and filter operators are allow-listed. `order_by` is one real field plus `asc` or `desc`. Allowed operators: `=`, `!=`, `>`, `<`, `>=`, `<=`, `like`, `not like`, `in`, `not in`, `between`, `is`. Aggregations: `sum`, `avg`, `min`, `max`, `count`.

## Desk assistant

**Enable AI Assistant** on MCP Settings turns on in-desk chat. The model must support OpenAI-style tool calling. Ollama, OpenAI, and any compatible `/v1/chat/completions` endpoint work. External MCP clients do not use this provider. They bring their own model.

Chat sessions and messages are stored as **MCP Chat Session** and **MCP Chat Message**. A user sees their own sessions. System Manager sees all.

## Site settings

**MCP Settings** (System Manager):

- **Enable AI Assistant** — desk chat, using the LLM Provider tab.
- **Enable Query Logging** — assistant questions and answers in **MCP Query Log**. The answer is stored. Raw document dumps are not given their own columns.
- **Enable Tool Logging** — each MCP and assistant tool call in **MCP Tool Log**: user, connector, tool, DocType, duration, redacted arguments, and a short result. Not the document body.
- **Enable Reports Tool** — `list_reports` and `run_report`.
- **Enable Semantic Search**, **Qdrant Enabled**, and **Embedding Model** — all three, plus a reachable Qdrant URL, are required before vector search runs. Embeddings are plain HTTP. Changing the embedding model changes vector size. Use **Reset Vector Index** after a model change. **Test Embedding** and **Reindex** are on the same form.
- **OAuth Client** — client id and secret for a chat app that cannot register itself.
- Document Actions — the site-wide ceiling for Create, Read, Update, Submit, Cancel, and Delete.
- **Maximum Result Rows**, **Query Timeout (seconds)**, **Schema Cache TTL (minutes)**, **Log Retention (days)**, **Default Rate Limit**.
- **MCP Allowed Origins** — CORS for browser clients. `*` allows any origin.

The first time semantic search is fully configured, a background job indexes business DocTypes and their text fields. Later saves update the index. Search hits are candidates. The instructions tell the model to call `get_record` before treating a field as fact, and hits the user cannot read are dropped.

Logs older than **Log Retention (days)** are deleted by the daily job. `0` keeps them.

## Security

- Connector keys are SHA-256 hashed. An encrypted copy is kept so the Connect page can show the URL. Regenerating a key kills the old URL and the old header immediately.
- OAuth codes and tokens are stored as hashes. Authorization codes expire in 10 minutes and can be used once. Client secrets are hashed, and the default secret is also encrypted for the OAuth Client button.
- Dynamic registration is limited to 30 clients per IP per hour.
- Guest cannot open connectors, the assistant, or the OAuth client secret.
- MariaDB `max_statement_time` is set from **Query Timeout** around each tool call.
- Cancel of a submitted document and delete of a draft are separate tools. A submitted document must be cancelled before it can be deleted, and only when those switches are on.
- The server URL is a secret. It contains the key. Prefer the public https host, and regenerate the key if the URL is copied into a place you do not control.

## Development

```bash
bench --site <site> run-tests --app frappe_mcp
bench --site <site> clear-cache
```

Desk form and list scripts are read from the DocType files. After changing `mcp_connector_list.js` or `mcp_settings.js`, bump that DocType's `modified` timestamp and clear the site cache so the browser drops its localStorage copy. A hard refresh alone does not.
