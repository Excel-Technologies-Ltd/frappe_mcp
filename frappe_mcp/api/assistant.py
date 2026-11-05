# Copyright (c) 2026, Shaid Azmin and contributors
# For license information, please see license.txt

import frappe

from frappe_mcp.ai.assistant import ask as run_ask
from frappe_mcp.ai.chat import delete_session, list_sessions, session_detail


@frappe.whitelist()
def ask(query, session_name=None):
	return run_ask(query, session_name)


@frappe.whitelist()
def list_chat_sessions():
	if frappe.session.user in ("", "Guest"):
		frappe.throw(frappe._("Login required."), frappe.PermissionError)
	return list_sessions()


@frappe.whitelist()
def get_chat_session(session_name):
	if frappe.session.user in ("", "Guest"):
		frappe.throw(frappe._("Login required."), frappe.PermissionError)
	return session_detail(session_name)


@frappe.whitelist()
def delete_chat_session(session_name):
	if frappe.session.user in ("", "Guest"):
		frappe.throw(frappe._("Login required."), frappe.PermissionError)
	delete_session(session_name)
	return {"deleted": session_name}
