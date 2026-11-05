# Copyright (c) 2026, Shaid Azmin and contributors
# For license information, please see license.txt

"""Public OAuth routes. MCP clients discover these from the 401 header."""

from __future__ import annotations

import frappe

from frappe_mcp.mcp.oauth import (
	authorization_server_metadata,
	authorize,
	exchange,
	html_page,
	json_response,
	protected_resource_metadata,
	register_client,
	request_params,
)


PATHS = {
	".well-known/oauth-protected-resource",
	".well-known/oauth-protected-resource/mcp",
	".well-known/oauth-authorization-server",
	".well-known/openid-configuration",
	"register",
	"oauth/register",
	"oauth/authorize",
	"oauth/token",
}


class OAuthPage:
	def __init__(self, path=None, http_status_code=None):
		self.path = (path or "").strip("/")
		self.http_status_code = http_status_code or 200

	def can_render(self):
		return self.path in PATHS

	def render(self):
		try:
			return self._render()
		except Exception:
			frappe.log_error(title="MCP OAuth failed")
			return json_response({"error": "server_error", "error_description": "OAuth request failed."}, 500)

	def _render(self):
		method = getattr(frappe.request, "method", "GET")
		if self.path in (
			".well-known/oauth-protected-resource",
			".well-known/oauth-protected-resource/mcp",
		):
			if method != "GET":
				return json_response({"error": "invalid_request"}, 405)
			return json_response(protected_resource_metadata(), 200)
		if self.path in (".well-known/oauth-authorization-server", ".well-known/openid-configuration"):
			if method != "GET":
				return json_response({"error": "invalid_request"}, 405)
			return json_response(authorization_server_metadata(), 200)
		if self.path in ("register", "oauth/register"):
			if method != "POST":
				return json_response({"error": "invalid_request"}, 405)
			status, body = register_client(request_params())
			return json_response(body, status)
		if self.path == "oauth/token":
			if method != "POST":
				return json_response({"error": "invalid_request"}, 405)
			status, body = exchange(request_params())
			return json_response(body, status)
		if self.path == "oauth/authorize":
			if method not in ("GET", "POST"):
				return json_response({"error": "invalid_request"}, 405)
			result = authorize(request_params())
			if isinstance(result, tuple):
				body, status = result
				if str(body).lstrip().startswith("<"):
					from frappe_mcp.mcp.oauth import frappe_response

					return frappe_response(body, status, "text/html")
				return body
			return result
		return frappe_response_html(html_page("Not found", "This OAuth address is not used."), 404)


def frappe_response_html(body, status):
	from frappe_mcp.mcp.oauth import frappe_response

	return frappe_response(body, status, "text/html")
