# Copyright (c) 2026, Shaid Azmin and contributors
# For license information, please see license.txt

"""Tool catalog shared by the MCP server and the desk assistant.

Tools the current policy forbids are omitted from tools/list so a model
does not invent a cancel or delete call. call_tool checks the policy
again before running anything.
"""

from __future__ import annotations

import json

import frappe

from frappe_mcp.policy import current_policy
from frappe_mcp.tools import read as read_tools
from frappe_mcp.tools import reports as report_tools
from frappe_mcp.tools import write as write_tools
from frappe_mcp.tools.guards import apply_query_timeout, clear_query_timeout

_OBJECT = "object"


def _schema(properties, required=None):
	data = {"type": _OBJECT, "properties": properties, "additionalProperties": False}
	if required:
		data["required"] = required
	return data


def _str(description):
	return {"type": "string", "description": description}


def _bool(description):
	return {"type": "boolean", "description": description}


def _int(description):
	return {"type": "integer", "description": description}


_CONFIRM = _bool(
	"false (default) previews and writes nothing. true performs the action, and only after the user explicitly agreed."
)

TOOLS = [
	{
		"name": "whoami",
		"description": "Who this connector runs as, which document actions are enabled, and today's date. Call this first when unsure what you may do.",
		"policy": "always",
		"schema": _schema({}),
		"fn": lambda **_kwargs: read_tools.whoami(),
	},
	{
		"name": "resolve_date_range",
		"description": "Turn a relative date phrase into inclusive from_date and to_date (YYYY-MM-DD), computed on the server. Use this before filtering. Never guess dates.",
		"policy": "read",
		"schema": _schema({"phrase": _str("today, yesterday, this month, last month, this quarter, last N days, year to date, and similar.")}, ["phrase"]),
		"fn": lambda phrase, **_kwargs: read_tools.resolve_date_range(phrase),
	},
	{
		"name": "list_doctypes",
		"description": "DocTypes this user may read. Pass search when you have a keyword. An empty search returns only the first 30.",
		"policy": "read",
		"schema": _schema({"search": _str("Optional substring matched against DocType name and module.")}),
		"fn": lambda search="", **_kwargs: read_tools.list_doctypes(search or ""),
	},
	{
		"name": "get_schema",
		"description": "Fields, links, and child tables for one DocType. Call this before filtering or writing so field names are real.",
		"policy": "read",
		"schema": _schema(
			{"doctype": _str("Exact DocType name."), "search": _str("Optional substring matched against fieldname and label.")},
			["doctype"],
		),
		"fn": lambda doctype, search="", **_kwargs: read_tools.get_schema(doctype, search or ""),
	},
	{
		"name": "get_permissions",
		"description": "Frappe permissions and connector switches for one DocType. Use this before telling the user you can create, update, submit, cancel, or delete.",
		"policy": "read",
		"schema": _schema({"doctype": _str("Exact DocType name.")}, ["doctype"]),
		"fn": lambda doctype, **_kwargs: read_tools.get_permissions(doctype),
	},
	{
		"name": "get_record",
		"description": "Fetch one document by id. Leave doctype blank to resolve it from the naming series. Password fields are masked.",
		"policy": "read",
		"schema": _schema(
			{"identifier": _str("Document name / id."), "doctype": _str("DocType. Optional when the id is unique.")},
			["identifier"],
		),
		"fn": lambda identifier, doctype="", **_kwargs: read_tools.get_record(identifier, doctype or ""),
	},
	{
		"name": "get_child_records",
		"description": "Rows of a parent document's child table. Pass child_doctype when the parent has more than one.",
		"policy": "read",
		"schema": _schema(
			{
				"parent_identifier": _str("Parent document name."),
				"child_doctype": _str("Child DocType. Optional when there is only one."),
				"parent_doctype": _str("Parent DocType. Optional."),
			},
			["parent_identifier"],
		),
		"fn": lambda parent_identifier, child_doctype="", parent_doctype="", **_kwargs: read_tools.get_child_records(
			parent_identifier, child_doctype or "", parent_doctype or ""
		),
	},
	{
		"name": "count_records",
		"description": "Exact permission-aware count. Prefer this for how-many questions.",
		"policy": "read",
		"schema": _schema(
			{
				"doctype": _str("Exact DocType name."),
				"filters_json": _str('JSON object. Example: {"status": "Open"} or {"grand_total": [">", 1000]}.'),
			},
			["doctype"],
		),
		"fn": lambda doctype, filters_json="{}", **_kwargs: read_tools.count_records(doctype, filters_json or "{}"),
	},
	{
		"name": "query_records",
		"description": "List matching documents. fields_json is a JSON list of real fieldnames. Results are capped by MCP Settings.",
		"policy": "read",
		"schema": _schema(
			{
				"doctype": _str("Exact DocType name."),
				"filters_json": _str("JSON object of filters."),
				"fields_json": _str('JSON list of fieldnames, e.g. ["name", "status"].'),
				"limit": _int("Maximum rows. Capped by site settings."),
				"order_by": _str("One fieldname, optionally followed by asc or desc."),
			},
			["doctype"],
		),
		"fn": lambda doctype, filters_json="{}", fields_json="[]", limit=20, order_by="", **_kwargs: read_tools.query_records(
			doctype, filters_json or "{}", fields_json or "[]", limit or 20, order_by or ""
		),
	},
	{
		"name": "aggregate_field",
		"description": "sum, avg, min, max, or count of one numeric field. Permission-aware.",
		"policy": "read",
		"schema": _schema(
			{
				"doctype": _str("Exact DocType name."),
				"fieldname": _str("Numeric fieldname. Ignored for count."),
				"operation": _str("sum, avg, min, max, or count."),
				"filters_json": _str("JSON object of filters."),
			},
			["doctype", "fieldname"],
		),
		"fn": lambda doctype, fieldname, operation="sum", filters_json="{}", **_kwargs: read_tools.aggregate_field(
			doctype, fieldname, operation or "sum", filters_json or "{}"
		),
	},
	{
		"name": "search_link",
		"description": "Resolve a partial title to real document names before writing a Link field. Uses Frappe link search and this user's permissions.",
		"policy": "read",
		"schema": _schema(
			{"doctype": _str("Link target DocType."), "text": _str("Text the user typed."), "limit": _int("Max matches.")},
			["doctype", "text"],
		),
		"fn": lambda doctype, text, limit=20, **_kwargs: read_tools.search_link(doctype, text, limit or 20),
	},
	{
		"name": "get_comments",
		"description": "Comments on one document.",
		"policy": "read",
		"schema": _schema(
			{"doctype": _str("DocType."), "name": _str("Document name."), "limit": _int("Max comments.")},
			["doctype", "name"],
		),
		"fn": lambda doctype, name, limit=20, **_kwargs: read_tools.get_comments(doctype, name, limit or 20),
	},
	{
		"name": "get_attachments",
		"description": "File metadata attached to one document. Does not return private file bytes.",
		"policy": "read",
		"schema": _schema({"doctype": _str("DocType."), "name": _str("Document name.")}, ["doctype", "name"]),
		"fn": lambda doctype, name, **_kwargs: read_tools.get_attachments(doctype, name),
	},
	{
		"name": "get_linked_documents",
		"description": "Documents linked to this one, permission-filtered, capped per DocType.",
		"policy": "read",
		"schema": _schema({"doctype": _str("DocType."), "name": _str("Document name.")}, ["doctype", "name"]),
		"fn": lambda doctype, name, **_kwargs: read_tools.get_linked_documents(doctype, name),
	},
	{
		"name": "list_reports",
		"description": "Saved Query and Script Reports this user may run. Always pass search. Disabled when Enable Reports Tool is off.",
		"policy": "reports",
		"schema": _schema({"search": _str("Substring of report name, module, or reference DocType.")}),
		"fn": lambda search="", **_kwargs: report_tools.list_reports(search or ""),
	},
	{
		"name": "run_report",
		"description": "Run a Query or Script Report through Frappe's report engine. Common company and fiscal-year filters are filled when omitted. Report Builder reports are refused.",
		"policy": "reports",
		"schema": _schema(
			{"report_name": _str("Exact report name from list_reports."), "filters_json": _str("JSON object of report filters.")},
			["report_name"],
		),
		"fn": lambda report_name, filters_json="{}", **_kwargs: report_tools.run_report(report_name, filters_json or "{}"),
	},
	{
		"name": "semantic_search_records",
		"description": "Find records by meaning using the Qdrant index. Results are unverified candidates. Always follow with get_record. Available only when semantic search is fully configured.",
		"policy": "semantic",
		"schema": _schema(
			{
				"query_text": _str("Natural language description of the record."),
				"doctype": _str("Optional DocType limit."),
				"limit": _int("Max candidates."),
			},
			["query_text"],
		),
		"fn": lambda query_text, doctype="", limit=5, **_kwargs: report_tools.semantic_search_records(
			query_text, doctype or "", limit or 5
		),
	},
	{
		"name": "semantic_search_doctypes",
		"description": "Find which DocType a vague question is about, using the vector catalog. Confirm with get_schema before querying.",
		"policy": "semantic",
		"schema": _schema(
			{"query_text": _str("What the user is asking about."), "limit": _int("Max DocTypes.")},
			["query_text"],
		),
		"fn": lambda query_text, limit=5, **_kwargs: report_tools.semantic_search_doctypes(query_text, limit or 5),
	},
	{
		"name": "create_record",
		"description": "Create a draft document. First call must use confirm=false and returns a preview or the missing required fields. confirm=true only after the user explicitly agrees. Never submits.",
		"policy": "create",
		"schema": _schema(
			{
				"doctype": _str("DocType to create."),
				"values_json": _str("JSON object of field values. Child tables are lists of objects."),
				"confirm": _CONFIRM,
			},
			["doctype"],
		),
		"fn": lambda doctype, values_json="{}", confirm=False, **_kwargs: write_tools.create_record(
			doctype, values_json or "{}", confirm
		),
	},
	{
		"name": "update_record",
		"description": "Update fields on an existing document. confirm=false previews. Does not submit, cancel, or delete.",
		"policy": "update",
		"schema": _schema(
			{
				"doctype": _str("DocType."),
				"name": _str("Document name."),
				"values_json": _str("JSON object of fields to change."),
				"confirm": _CONFIRM,
			},
			["doctype", "name", "values_json"],
		),
		"fn": lambda doctype, name, values_json, confirm=False, **_kwargs: write_tools.update_record(
			doctype, name, values_json, confirm
		),
	},
	{
		"name": "add_comment",
		"description": "Add a comment on a document the user can read. confirm=false previews.",
		"policy": "create",
		"schema": _schema(
			{
				"doctype": _str("DocType."),
				"name": _str("Document name."),
				"content": _str("Plain text comment."),
				"confirm": _CONFIRM,
			},
			["doctype", "name", "content"],
		),
		"fn": lambda doctype, name, content, confirm=False, **_kwargs: write_tools.add_comment(
			doctype, name, content, confirm
		),
	},
	{
		"name": "get_workflow",
		"description": "Current workflow state and the actions this user may take. Actions that would submit or cancel are marked blocked when those switches are off.",
		"policy": "read",
		"schema": _schema({"doctype": _str("DocType."), "name": _str("Document name.")}, ["doctype", "name"]),
		"fn": lambda doctype, name, **_kwargs: write_tools.get_workflow(doctype, name),
	},
	{
		"name": "apply_workflow_action",
		"description": "Apply one workflow action from get_workflow. confirm=false previews. Submit and cancel actions stay blocked unless those switches are on.",
		"policy": "update",
		"schema": _schema(
			{
				"doctype": _str("DocType."),
				"name": _str("Document name."),
				"action": _str("Action label from get_workflow."),
				"confirm": _CONFIRM,
			},
			["doctype", "name", "action"],
		),
		"fn": lambda doctype, name, action, confirm=False, **_kwargs: write_tools.apply_workflow_action(
			doctype, name, action, confirm
		),
	},
	{
		"name": "submit_document",
		"description": "Submit a draft. Available only when Submit is enabled on MCP Settings and on this connector, and the user has submit permission.",
		"policy": "submit",
		"schema": _schema(
			{"doctype": _str("Submittable DocType."), "name": _str("Document name."), "confirm": _CONFIRM},
			["doctype", "name"],
		),
		"fn": lambda doctype, name, confirm=False, **_kwargs: write_tools.submit_document(doctype, name, confirm),
	},
	{
		"name": "cancel_document",
		"description": "Cancel a submitted document. Available only when Cancel is enabled on MCP Settings and on this connector, and the user has cancel permission.",
		"policy": "cancel",
		"schema": _schema(
			{"doctype": _str("Submittable DocType."), "name": _str("Document name."), "confirm": _CONFIRM},
			["doctype", "name"],
		),
		"fn": lambda doctype, name, confirm=False, **_kwargs: write_tools.cancel_document(doctype, name, confirm),
	},
	{
		"name": "delete_document",
		"description": "Delete a document. Available only when Delete is enabled on MCP Settings and on this connector, and the user has delete permission. Submitted documents must be cancelled first.",
		"policy": "delete",
		"schema": _schema(
			{"doctype": _str("DocType."), "name": _str("Document name."), "confirm": _CONFIRM},
			["doctype", "name"],
		),
		"fn": lambda doctype, name, confirm=False, **_kwargs: write_tools.delete_document(doctype, name, confirm),
	},
]

_BY_NAME = {tool["name"]: tool for tool in TOOLS}


def _policy_allows(tool: dict) -> bool:
	policy = current_policy()
	flag = tool["policy"]
	if flag == "always":
		return True
	if flag == "reports":
		return bool(policy.get("reports")) and bool(policy.get("allow_read"))
	if flag == "semantic":
		return bool(policy.get("semantic")) and bool(policy.get("allow_read"))
	return bool(policy.get(f"allow_{flag}"))


def visible_tools() -> list[dict]:
	return [tool for tool in TOOLS if _policy_allows(tool)]


def tool_names() -> list[str]:
	return [tool["name"] for tool in visible_tools()]


def mcp_tool_list() -> list[dict]:
	return [
		{"name": tool["name"], "description": tool["description"], "inputSchema": tool["schema"]}
		for tool in visible_tools()
	]


def openai_tool_list() -> list[dict]:
	return [
		{
			"type": "function",
			"function": {
				"name": tool["name"],
				"description": tool["description"],
				"parameters": tool["schema"],
			},
		}
		for tool in visible_tools()
	]


def call_tool(name: str, arguments: dict | None) -> dict:
	spec = _BY_NAME.get(name)
	if not spec:
		return {"error": f"Unknown tool '{name}'."}
	if not _policy_allows(spec):
		return {
			"error": (
				f"'{name}' is disabled. Create, Read, and Update are on by default. "
				"Cancel, Delete, and Submit require both MCP Settings and the connector to allow them."
			)
		}
	arguments = arguments or {}
	if isinstance(arguments, str):
		try:
			arguments = json.loads(arguments)
		except json.JSONDecodeError:
			return {"error": "Tool arguments must be a JSON object."}
	if not isinstance(arguments, dict):
		return {"error": "Tool arguments must be a JSON object."}
	props = spec["schema"]["properties"]
	kwargs = {key: value for key, value in arguments.items() if key in props}
	missing = [key for key in spec["schema"].get("required") or [] if kwargs.get(key) in (None, "")]
	if missing:
		return {"error": "Missing arguments: " + ", ".join(missing)}
	savepoint = "mcp_tool_call"
	try:
		apply_query_timeout()
		frappe.db.savepoint(savepoint)
		result = spec["fn"](**kwargs)
		if not isinstance(result, dict):
			result = {"result": result}
		frappe.db.release_savepoint(savepoint)
		return result
	except frappe.PermissionError as exc:
		frappe.db.rollback(save_point=savepoint)
		return {"error": str(exc), "permission_denied": True}
	except frappe.ValidationError as exc:
		frappe.db.rollback(save_point=savepoint)
		return {"error": str(exc)}
	except Exception:
		frappe.db.rollback(save_point=savepoint)
		frappe.log_error(title=f"MCP tool failed: {name}")
		return {"error": f"{name} failed. The site log has the traceback. No partial guess was returned."}
	finally:
		clear_query_timeout()
