# Copyright (c) 2026, Shaid Azmin and contributors
# For license information, please see license.txt

"""Bearer auth for /mcp only.

Frappe rejects a Bearer header when the session is still Guest. This hook
runs inside validate_auth, before that rejection, and only on the MCP path.
A connector token never authenticates any other URL.
"""

from __future__ import annotations

import hashlib
import ipaddress

import frappe

from frappe_mcp.policy import connector_policy


def is_mcp_path(path: str | None = None) -> bool:
	path = path if path is not None else getattr(frappe.request, "path", "") or ""
	path = path.rstrip("/") or "/"
	return path == "/mcp" or path.startswith("/mcp/")


def _token_from_header(name: str) -> str:
	value = (frappe.get_request_header(name, "") or "").strip()
	if value.lower().startswith("bearer "):
		value = value.split(" ", 1)[1].strip()
	return value


def token_from_path(path: str | None = None) -> str:
	"""Zoho-style URL: /mcp/<token>/message. The key is the path, not a header."""
	from urllib.parse import unquote

	path = path if path is not None else getattr(frappe.request, "path", "") or ""
	parts = [unquote(part) for part in path.strip("/").split("/") if part]
	if len(parts) < 2 or parts[0] != "mcp" or not parts[1].startswith("fmcp_"):
		return ""
	if len(parts) == 2 or (len(parts) == 3 and parts[2] == "message"):
		return parts[1]
	return ""


def bearer_token() -> str:
	"""Path key first, so a pasted server URL works with no header."""
	token = token_from_path()
	if token:
		return token
	for name in ("X-Api-Key", "X-Auth-Token", "X-Frappe-MCP-Token", "Authorization"):
		token = _token_from_header(name)
		if token:
			return token
	return ""


def token_hash(token: str) -> str:
	return hashlib.sha256(token.encode()).hexdigest()


def ip_allowed(allowlist: str | None, ip: str | None) -> bool:
	raw = (allowlist or "").strip()
	if not raw:
		return True
	if not ip:
		return False
	try:
		address = ipaddress.ip_address(ip)
	except ValueError:
		return False
	for part in raw.replace(",", " ").split():
		try:
			if "/" in part:
				if address in ipaddress.ip_network(part, strict=False):
					return True
			elif address == ipaddress.ip_address(part):
				return True
		except ValueError:
			continue
	return False


def find_connector(token: str):
	if not token or not frappe.db.exists("DocType", "MCP Connector"):
		return None
	name = frappe.db.get_value("MCP Connector", {"token_hash": token_hash(token)}, "name")
	if name:
		return frappe.get_doc("MCP Connector", name)
	from frappe_mcp.mcp.oauth import connector_for_access_token

	return connector_for_access_token(token)


def connector_is_usable(connector) -> str | None:
	"""None when the connector may be used, otherwise a short reason."""
	if not connector.get("enabled"):
		return "disabled"
	if connector.get("expires_on") and str(connector.expires_on) < str(frappe.utils.today()):
		return "expired"
	user = connector.get("user")
	if not user or not frappe.db.get_value("User", user, "enabled"):
		return "user"
	ip = getattr(frappe.local, "request_ip", None) or getattr(frappe.request, "remote_addr", None)
	if not ip_allowed(connector.get("ip_allowlist"), ip):
		return "ip"
	return None


def authenticate_request():
	"""auth_hooks entry. Sets the session user to the connector owner."""
	if not is_mcp_path():
		return
	token = bearer_token()
	if not token:
		return
	try:
		connector = find_connector(token)
	except Exception:
		frappe.log_error(title="MCP auth lookup failed")
		return
	if not connector or connector_is_usable(connector):
		return
	frappe.set_user(connector.user)
	frappe.flags.mcp_connector = connector.name
	frappe.flags.mcp_policy = connector_policy(connector)
	frappe.flags.mcp_source = "MCP"


def touch_connector(name: str) -> None:
	if not name:
		return
	cache_key = f"frappe_mcp:touch:{name}"
	if frappe.cache().get_value(cache_key, expires=True):
		return
	frappe.db.set_value("MCP Connector", name, "last_used", frappe.utils.now_datetime(), update_modified=False)
	frappe.cache().set_value(cache_key, 1, expires_in_sec=60)


def rate_limited(connector_name: str, limit: int) -> bool:
	if not limit or int(limit) <= 0:
		return False
	bucket = frappe.utils.now_datetime().strftime("%Y%m%d%H%M")
	key = f"frappe_mcp:rate:{connector_name}:{bucket}"
	current = int(frappe.cache().get_value(key, expires=True) or 0)
	if current >= int(limit):
		return True
	frappe.cache().set_value(key, current + 1, expires_in_sec=90)
	return False
