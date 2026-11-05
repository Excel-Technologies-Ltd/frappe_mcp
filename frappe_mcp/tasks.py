# Copyright (c) 2026, Shaid Azmin and contributors
# For license information, please see license.txt

"""Scheduled cleanup. Tool and query logs are operational data, not a
permanent archive. Retention comes from MCP Settings.
"""

import frappe


def daily():
	days = frappe.db.get_single_value("MCP Settings", "log_retention_days") or 90
	days = int(days)
	if days <= 0:
		return
	cutoff = frappe.utils.add_days(frappe.utils.nowdate(), -days)
	for doctype in ("MCP Tool Log", "MCP Query Log"):
		if not frappe.db.exists("DocType", doctype):
			continue
		names = frappe.get_all(
			doctype,
			filters={"creation": ["<", cutoff]},
			pluck="name",
			limit_page_length=5000,
		)
		for name in names:
			frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)
