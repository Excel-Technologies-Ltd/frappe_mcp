# Copyright (c) 2026, Shaid Azmin and contributors
# For license information, please see license.txt

import frappe


def bootinfo(bootinfo):
	enabled = 0
	try:
		enabled = frappe.db.get_single_value("MCP Settings", "enable_ai_assistant") or 0
	except Exception:
		enabled = 0
	bootinfo.frappe_mcp = {"assistant_enabled": 1 if enabled else 0}
