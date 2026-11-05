# Copyright (c) 2026, Shaid Azmin and contributors
# For license information, please see license.txt

import frappe
from frappe import _

from frappe_mcp.mcp.oauth import default_client_html


def _require_manager():
	user = frappe.session.user
	if user == "Administrator" or "System Manager" in frappe.get_roles(user):
		return
	frappe.throw(_("Only a System Manager or Administrator can view the OAuth client."), frappe.PermissionError)


@frappe.whitelist()
def default_client():
	_require_manager()
	return {"html": default_client_html()}
