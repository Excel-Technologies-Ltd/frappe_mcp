# Copyright (c) 2026, Shaid Azmin and contributors
# For license information, please see license.txt

"""Effective tool policy.

Site MCP Settings is the ceiling. A connector can only turn a write off,
or turn Cancel / Delete / Submit on when the site already allows it.
Create, Read, and Update default on. Cancel and Delete default off.
Frappe document permissions are a second gate inside each tool.
"""

from __future__ import annotations

import frappe

from frappe_mcp.settings import as_bool, get_settings

_ACTIONS = ("read", "create", "update", "cancel", "delete", "submit")


def _split_lines(value: str | None) -> list[str]:
	if not value:
		return []
	parts = []
	for line in str(value).replace(",", "\n").splitlines():
		name = line.strip()
		if name:
			parts.append(name)
	return parts


def site_policy() -> dict:
	settings = get_settings()
	semantic = False
	try:
		from frappe_mcp.ai.embeddings import embedding_available

		semantic = embedding_available()
	except Exception:
		semantic = False
	return {
		"allow_read": as_bool(settings.get("allow_read")),
		"allow_create": as_bool(settings.get("allow_create")),
		"allow_update": as_bool(settings.get("allow_update")),
		"allow_cancel": as_bool(settings.get("allow_cancel")),
		"allow_delete": as_bool(settings.get("allow_delete")),
		"allow_submit": as_bool(settings.get("allow_submit")),
		"reports": as_bool(settings.get("enable_reports_tool")),
		"semantic": semantic,
		"allowed_doctypes": [],
		"blocked_doctypes": [],
		"connector": None,
		"source": "settings",
	}


def connector_policy(connector) -> dict:
	"""Site ceiling AND the connector's own switches."""
	base = site_policy()
	return {
		"allow_read": base["allow_read"] and as_bool(connector.get("allow_read")),
		"allow_create": base["allow_create"] and as_bool(connector.get("allow_create")),
		"allow_update": base["allow_update"] and as_bool(connector.get("allow_update")),
		"allow_cancel": base["allow_cancel"] and as_bool(connector.get("allow_cancel")),
		"allow_delete": base["allow_delete"] and as_bool(connector.get("allow_delete")),
		"allow_submit": base["allow_submit"] and as_bool(connector.get("allow_submit")),
		"reports": base["reports"],
		"semantic": base["semantic"],
		"allowed_doctypes": _split_lines(connector.get("allowed_doctypes")),
		"blocked_doctypes": _split_lines(connector.get("blocked_doctypes")),
		"connector": connector.get("name"),
		"source": "connector",
	}


def current_policy() -> dict:
	policy = getattr(frappe.flags, "mcp_policy", None)
	if policy:
		return policy
	return site_policy()


def bind_policy(policy: dict) -> None:
	frappe.flags.mcp_policy = policy


def action_allowed(action: str) -> bool:
	return bool(current_policy().get(f"allow_{action}"))


def assert_action(action: str) -> None:
	if action not in _ACTIONS:
		frappe.throw(frappe._("Unknown action {0}.").format(action))
	if action_allowed(action):
		return
	frappe.throw(
		frappe._(
			"{0} is turned off. Create, Read, and Update are allowed by default. "
			"Cancel, Delete, and Submit run only when MCP Settings and this "
			"connector both allow them, and the user has that Frappe permission."
		).format(action.capitalize())
	)


def doctype_in_scope(doctype: str) -> bool:
	policy = current_policy()
	blocked = {name.lower() for name in policy.get("blocked_doctypes") or []}
	if doctype.lower() in blocked:
		return False
	allowed = policy.get("allowed_doctypes") or []
	if not allowed:
		return True
	return doctype.lower() in {name.lower() for name in allowed}
