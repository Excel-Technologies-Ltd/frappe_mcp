# Copyright (c) 2026, Shaid Azmin and contributors
# For license information, please see license.txt

"""Website page renderer for POST/GET /mcp.

Returns a raw JSON-RPC Response. Frappe's /api/method wrapper is not used,
because MCP clients reject the {"message": ...} envelope.
"""

from __future__ import annotations

import json

from werkzeug.wrappers import Response

import frappe

from frappe_mcp.mcp.auth import is_mcp_path, rate_limited, touch_connector
from frappe_mcp.mcp.oauth import www_authenticate
from frappe_mcp import __version__
from frappe_mcp.mcp.protocol import INSTRUCTIONS, SERVER_NAME, handle_message
from frappe_mcp.settings import get_settings


class MCPPage:
	def __init__(self, path=None, http_status_code=None):
		self.path = (path or "").strip("/")
		self.http_status_code = http_status_code or 200

	def can_render(self):
		return self.path == "mcp" or self.path.startswith("mcp/")

	def render(self):
		try:
			return self._render()
		except Exception:
			frappe.log_error(title="MCP renderer failed")
			return _json({"jsonrpc": "2.0", "id": None, "error": {"code": -32603, "message": "Internal error"}}, 500)

	def _render(self):
		request = frappe.request
		origin = request.headers.get("Origin")
		if request.method == "GET":
			body = {
				"server": SERVER_NAME,
				"version": __version__,
				"endpoint": frappe.utils.get_url("/mcp"),
				"transport": "streamable-http",
				"auth": "OAuth, or Authorization: Bearer <connector token>",
				"instructions": INSTRUCTIONS,
			}
			return _json(body, 200, origin)
		if request.method == "DELETE":
			response = Response(status=200)
			_cors(response, origin)
			return response
		if request.method != "POST":
			response = _json({"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "POST required"}}, 405, origin)
			response.headers["Allow"] = "GET, POST, DELETE"
			return response
		if frappe.session.user in ("", "Guest") or not getattr(frappe.flags, "mcp_connector", None):
			return _json(
				{"jsonrpc": "2.0", "id": None, "error": {"code": -32001, "message": "Authentication required"}},
				401,
				origin,
				extra={"WWW-Authenticate": www_authenticate()},
			)
		connector_name = frappe.flags.mcp_connector
		connector = frappe.get_doc("MCP Connector", connector_name)
		raw_limit = connector.get("rate_limit_per_minute")
		if raw_limit == 0:
			limit = 0
		elif raw_limit:
			limit = int(raw_limit)
		else:
			limit = int(get_settings().get("default_rate_limit") or 120)
		if rate_limited(connector_name, limit):
			return _json(
				{"jsonrpc": "2.0", "id": None, "error": {"code": -32002, "message": "Rate limit exceeded"}},
				429,
				origin,
			)
		touch_connector(connector_name)
		raw = request.get_data(as_text=True) or ""
		try:
			message = json.loads(raw) if raw else None
		except json.JSONDecodeError:
			return _json({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}, 400, origin)
		if isinstance(message, list):
			return _json(
				{"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Batch requests are not supported. Send one JSON-RPC object per POST."}},
				400,
				origin,
			)
		result = handle_message(message)
		if result is None:
			response = Response(status=202)
			_cors(response, origin)
			return response
		return _json(result, 200, origin)


def _json(payload, status, origin=None, extra=None):
	response = Response(
		json.dumps(payload, default=str),
		status=status,
		mimetype="application/json",
	)
	_cors(response, origin)
	if extra:
		for key, value in extra.items():
			response.headers[key] = value
	return response


def _cors(response, origin):
	settings = get_settings()
	allowed = (settings.get("mcp_allowed_origins") or "*").strip()
	if not origin:
		return
	if allowed == "*":
		chosen = "*"
	else:
		items = {item.strip() for item in allowed.split(",") if item.strip()}
		if origin not in items:
			return
		chosen = origin
	response.headers["Access-Control-Allow-Origin"] = chosen
	response.headers["Access-Control-Allow-Headers"] = (
		"Authorization, Content-Type, MCP-Protocol-Version, Mcp-Session-Id, "
		"X-Api-Key, X-Auth-Token, X-Frappe-MCP-Token"
	)
	response.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
	response.headers["Vary"] = "Origin"


def is_request_mcp():
	return is_mcp_path()
