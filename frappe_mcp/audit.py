# Copyright (c) 2026, Shaid Azmin and contributors
# For license information, please see license.txt

"""Query and tool logs. Arguments are redacted. Document bodies are not stored."""

from __future__ import annotations

import json

import frappe

from frappe_mcp.settings import get_settings
from frappe_mcp.tools.guards import SENSITIVE_NAMES

_MAX_ARG_CHARS = 4000


def _redact(value):
	if isinstance(value, dict):
		clean = {}
		for key, item in value.items():
			if str(key).lower() in SENSITIVE_NAMES or "password" in str(key).lower() or "token" in str(key).lower():
				clean[key] = "***"
			else:
				clean[key] = _redact(item)
		return clean
	if isinstance(value, list):
		return [_redact(item) for item in value[:30]]
	if isinstance(value, str) and len(value) > 500:
		return value[:500] + "…"
	return value


def summarize_result(result: dict | None) -> str:
	if not isinstance(result, dict):
		return ""
	if result.get("error"):
		return str(result["error"])[:500]
	doctype = result.get("doctype") or ""
	name = result.get("name") or ""
	if result.get("created") and name:
		return f"created {doctype} {name}"
	if result.get("updated") and name:
		return f"updated {doctype} {name}"
	if result.get("submitted"):
		return f"submitted {doctype} {name}"
	if result.get("cancelled"):
		return f"cancelled {doctype} {name}"
	if result.get("deleted"):
		return f"deleted {doctype} {name}"
	if "count" in result:
		return f"count {doctype}={result.get('count')}"
	if "count_returned" in result:
		return f"rows {doctype}={result.get('count_returned')}"
	if result.get("found") is False:
		return f"not found {doctype} {name or result.get('identifier') or ''}".strip()
	return doctype or "ok"


def log_tool_call(*, tool_name, arguments, result, duration, status, doctype=""):
	if not get_settings().get("enable_tool_logging"):
		return
	try:
		payload = json.dumps(_redact(arguments or {}), default=str)[:_MAX_ARG_CHARS]
		frappe.get_doc(
			{
				"doctype": "MCP Tool Log",
				"user": frappe.session.user,
				"connector": (frappe.flags.get("mcp_policy") or {}).get("connector"),
				"source": getattr(frappe.flags, "mcp_source", None) or "MCP",
				"tool_name": tool_name,
				"status": status,
				"doctype_name": doctype or (result or {}).get("doctype") or "",
				"duration_seconds": round(duration, 3),
				"arguments": payload,
				"result_summary": summarize_result(result),
			}
		).insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(title="MCP tool log failed")


def log_query(*, query, answer, status, duration, tool_call_count=0, doctypes_touched="", error=""):
	if not get_settings().get("enable_query_logging"):
		return
	try:
		frappe.get_doc(
			{
				"doctype": "MCP Query Log",
				"user": frappe.session.user,
				"connector": (frappe.flags.get("mcp_policy") or {}).get("connector"),
				"query": (query or "")[:4000],
				"answer": (answer or "")[:10000],
				"status": status,
				"duration_seconds": round(duration, 3),
				"tool_call_count": tool_call_count,
				"doctypes_touched": (doctypes_touched or "")[:1000],
				"error": (error or "")[:1000],
			}
		).insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(title="MCP query log failed")
