# Copyright (c) 2026, Shaid Azmin and contributors
# For license information, please see license.txt

import frappe
from frappe import _

from frappe_mcp.frappe_mcp.doctype.mcp_connector.mcp_connector import server_url


def _own_connector(create=False):
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("Sign in to see your MCP server URL."), frappe.PermissionError)
	name = frappe.db.get_value("MCP Connector", {"user": user}, "name")
	if name:
		doc = frappe.get_doc("MCP Connector", name)
		doc.check_permission("read")
		return doc
	if not create:
		return None
	full_name = frappe.db.get_value("User", user, "full_name") or user
	doc = frappe.get_doc(
		{
			"doctype": "MCP Connector",
			"user": user,
			"connector_name": full_name,
			"enabled": 1,
		}
	)
	doc.flags.skip_token_dialog = True
	doc.insert()
	return doc


def _stored_token(doc):
	if not doc:
		return ""
	return doc.get_password("api_token", raise_exception=False) or ""


def _payload(doc):
	token = _stored_token(doc)
	path = f"/mcp/{token}/message" if token else ""
	return {
		"name": doc.name if doc else "",
		"connector_name": doc.connector_name if doc else "",
		"path": path,
		"server_url": (frappe.utils.get_url().rstrip("/") + path) if path else "",
		"ready": 1 if token else 0,
	}


@frappe.whitelist()
def mine():
	"""The signed-in user's server URL. Creates their connector the first time."""
	return _payload(_own_connector(create=True))


@frappe.whitelist()
def regenerate():
	"""Replace the key inside the server URL. The previous URL stops immediately."""
	doc = _own_connector(create=True)
	doc.check_permission("write")
	doc.flags.skip_token_dialog = True
	token = doc.issue_token()
	doc.save()
	payload = _payload(doc)
	payload["server_url"] = server_url(token)
	payload["path"] = f"/mcp/{token}/message"
	payload["ready"] = 1
	return payload
