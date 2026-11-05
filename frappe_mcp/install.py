# Copyright (c) 2026, Shaid Azmin and contributors
# For license information, please see license.txt

import frappe


def before_migrate():
	ensure_role()


def after_migrate():
	ensure_connector_list_columns()
	backfill_connector_user_labels()
	from frappe_mcp.mcp.oauth import ensure_default_client

	ensure_default_client()


def after_install():
	ensure_role()
	if not frappe.db.exists("MCP Settings", "MCP Settings"):
		frappe.get_doc({"doctype": "MCP Settings"}).insert(ignore_permissions=True)
	frappe.enqueue(
		"frappe_mcp.ai.semantic.run_initial_index",
		queue="long",
		enqueue_after_commit=True,
	)


def ensure_role():
	if frappe.db.exists("Role", "MCP User"):
		return
	role = frappe.get_doc(
		{
			"doctype": "Role",
			"role_name": "MCP User",
			"desk_access": 1,
			"is_custom": 0,
		}
	)
	role.insert(ignore_permissions=True)


def ensure_connector_list_columns():
	"""ID, full name, email, status, connector name, last used."""
	if not frappe.db.table_exists("List View Settings"):
		return
	fields = frappe.as_json(
		[
			{"fieldname": "user_full_name"},
			{"fieldname": "user_email"},
			{"fieldname": "status_field"},
			{"fieldname": "connector_name"},
			{"fieldname": "last_used"},
		]
	)
	if frappe.db.exists("List View Settings", "MCP Connector"):
		doc = frappe.get_doc("List View Settings", "MCP Connector")
		doc.fields = fields
		doc.total_fields = "10"
		doc.save(ignore_permissions=True)
		return
	frappe.get_doc(
		{
			"doctype": "List View Settings",
			"name": "MCP Connector",
			"fields": fields,
			"total_fields": "10",
		}
	).insert(ignore_permissions=True)


def backfill_connector_user_labels():
	if not frappe.db.has_column("MCP Connector", "user_full_name"):
		return
	frappe.db.sql(
		"""
		UPDATE `tabMCP Connector` c
		INNER JOIN `tabUser` u ON u.name = c.user
		SET c.user_full_name = u.full_name,
			c.user_email = IFNULL(NULLIF(u.email, ''), u.name)
		"""
	)
