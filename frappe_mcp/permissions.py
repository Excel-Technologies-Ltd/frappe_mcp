# Copyright (c) 2026, Shaid Azmin and contributors
# For license information, please see license.txt

"""Row rules for connector and chat documents.

Returning None lets the DocType's own DocPerm decide. Returning False
denies. Guest never gets either doctype, even though role All would
otherwise match a website session.
"""

from __future__ import annotations

import frappe


def _is_manager(user: str) -> bool:
	return user == "Administrator" or "System Manager" in frappe.get_roles(user)


def connector_has_permission(doc, ptype=None, user=None):
	user = user or frappe.session.user
	if user == "Guest":
		return False
	if _is_manager(user):
		return True
	target = (doc.get("user") if doc else None) or user
	if target != user:
		return False
	return True


def connector_query_conditions(user=None):
	user = user or frappe.session.user
	if user == "Guest":
		return "1=0"
	if _is_manager(user):
		return ""
	return "`tabMCP Connector`.`user` = {0}".format(frappe.db.escape(user))


def chat_has_permission(doc, ptype=None, user=None):
	user = user or frappe.session.user
	if user == "Guest":
		return False
	return None


def chat_query_conditions(user=None):
	user = user or frappe.session.user
	if user == "Guest":
		return "1=0"
	if _is_manager(user):
		return ""
	return "`tabMCP Chat Session`.`owner` = {0}".format(frappe.db.escape(user))
