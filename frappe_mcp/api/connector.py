# Copyright (c) 2026, Shaid Azmin and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import cint
from frappe.utils.csvutils import build_csv_response

from frappe_mcp.frappe_mcp.doctype.mcp_connector.mcp_connector import config_with_token, server_url


def _require_manager():
	user = frappe.session.user
	if user == "Administrator" or "System Manager" in frappe.get_roles(user):
		return
	frappe.throw(
		_("Only a System Manager or Administrator can create or export connectors in bulk."),
		frappe.PermissionError,
	)


def _as_list(value):
	if not value:
		return []
	if isinstance(value, str):
		value = frappe.parse_json(value)
	if isinstance(value, str):
		value = [part.strip() for part in value.split(",") if part.strip()]
	return [row for row in value if row]


def _row(doc, token=None):
	row = {
		"name": doc.name,
		"connector_name": doc.connector_name,
		"user": doc.user,
		"enabled": doc.enabled,
		"endpoint": doc.endpoint,
		"token_prefix": doc.token_prefix,
		"last_used": str(doc.last_used or ""),
		"allow_read": doc.allow_read,
		"allow_create": doc.allow_create,
		"allow_update": doc.allow_update,
		"allow_submit": doc.allow_submit,
		"allow_cancel": doc.allow_cancel,
		"allow_delete": doc.allow_delete,
	}
	if token:
		row["token"] = token
		row["client_config"] = config_with_token(doc.connector_name, token)
	else:
		row["client_config"] = doc.client_config
	return row


@frappe.whitelist()
def regenerate_token(name):
	doc = frappe.get_doc("MCP Connector", name)
	doc.check_permission("write")
	doc.flags.skip_token_dialog = True
	token = doc.issue_token()
	doc.save()
	return {
		"token": token,
		"endpoint": doc.endpoint,
		"server_url": server_url(token),
		"client_config": doc.config_with_token(token),
		"name": doc.name,
	}


def _users_with_role(role):
	if not role:
		return None
	return frappe.get_all(
		"Has Role",
		filters={"role": role, "parenttype": "User"},
		pluck="parent",
		limit_page_length=0,
	)


def _matching_users(role=None):
	"""Enabled users except Guest. Role narrows the set. Users who already have a connector are skipped."""
	filters = {"enabled": 1, "name": ["!=", "Guest"]}
	if role:
		names = [name for name in _users_with_role(role) if name and name != "Guest"]
		if not names:
			return [], 0
		filters["name"] = ["in", names]
	users = frappe.get_all("User", filters=filters, pluck="name", limit_page_length=0)
	if not users:
		return [], 0
	existing = set(
		frappe.get_all(
			"MCP Connector",
			filters={"user": ["in", users]},
			pluck="user",
			limit_page_length=0,
		)
	)
	return [user for user in users if user not in existing], len(existing)


@frappe.whitelist()
def matching_users(role=None):
	_require_manager()
	users, skipped = _matching_users(role)
	return {"count": len(users), "skipped": skipped}


@frappe.whitelist()
def user_link_options(txt="", role=None, limit=100):
	_require_manager()
	filters = {"enabled": 1, "name": ["!=", "Guest"]}
	if role:
		names = [name for name in (_users_with_role(role) or []) if name and name != "Guest"]
		if not names:
			return []
		filters["name"] = ["in", names]
	or_filters = None
	if txt:
		or_filters = {
			"name": ["like", f"%{txt}%"],
			"full_name": ["like", f"%{txt}%"],
		}
	rows = frappe.get_all(
		"User",
		filters=filters,
		or_filters=or_filters,
		fields=["name", "full_name"],
		order_by="full_name asc",
		limit_page_length=cint(limit) or 100,
	)
	taken = set(frappe.get_all("MCP Connector", pluck="user", limit_page_length=0))
	return [
		{
			"value": row.name,
			"description": row.full_name or "",
			"taken": row.name in taken,
		}
		for row in rows
	]


@frappe.whitelist()
def bulk_create(users=None, connector_name=None, role=None, all_users=0):
	"""One connector per user. Tokens are returned once so the caller can download them."""
	_require_manager()
	connector_name = (connector_name or "").strip()
	if not connector_name:
		frappe.throw(_("Connector Name is required."))
	skipped = 0
	if cint(all_users):
		users, skipped = _matching_users(role)
	else:
		users = _as_list(users)
		if role:
			allowed = set(_matching_users(role)[0])
			users = [user for user in users if user in allowed]
	if not users:
		frappe.throw(
			_("No users to create. They may already have a connector, or none match this role.")
		)
	created = []
	seen = set()
	for user in users:
		if user in seen:
			continue
		seen.add(user)
		if user == "Guest" or not frappe.db.get_value("User", user, "enabled"):
			frappe.throw(_("User {0} is missing or disabled.").format(user))
		doc = frappe.get_doc(
			{
				"doctype": "MCP Connector",
				"connector_name": connector_name,
				"user": user,
				"enabled": 1,
				"allow_read": 1,
				"allow_create": 1,
				"allow_update": 1,
			}
		)
		doc.flags.skip_token_dialog = True
		doc.insert()
		created.append(_row(doc, doc.flags.plain_token))
	return {"created": created, "skipped": skipped}


@frappe.whitelist()
def export_connectors(names=None):
	"""CSV of connector metadata. Raw tokens are not stored, so they are not in this file."""
	_require_manager()
	names = _as_list(names)
	filters = {"name": ["in", names]} if names else None
	rows = frappe.get_all(
		"MCP Connector",
		filters=filters,
		fields=[
			"name",
			"connector_name",
			"user",
			"enabled",
			"endpoint",
			"token_prefix",
			"last_used",
			"allow_read",
			"allow_create",
			"allow_update",
			"allow_submit",
			"allow_cancel",
			"allow_delete",
		],
		order_by="name",
		limit_page_length=0,
	)
	columns = [
		"name",
		"connector_name",
		"user",
		"enabled",
		"endpoint",
		"token_prefix",
		"last_used",
		"allow_read",
		"allow_create",
		"allow_update",
		"allow_submit",
		"allow_cancel",
		"allow_delete",
	]
	data = [columns]
	for row in rows:
		data.append([row.get(column) for column in columns])
	build_csv_response(data, "MCP Connector")


@frappe.whitelist()
def regenerate_and_export(names):
	"""Replace tokens on the selected connectors and return them once for a CSV download."""
	_require_manager()
	names = _as_list(names)
	if not names:
		frappe.throw(_("Select at least one connector."))
	rows = []
	for name in names:
		doc = frappe.get_doc("MCP Connector", name)
		doc.check_permission("write")
		doc.flags.skip_token_dialog = True
		token = doc.issue_token()
		doc.save()
		rows.append(_row(doc, token))
	return rows
