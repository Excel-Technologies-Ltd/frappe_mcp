# Copyright (c) 2026, Shaid Azmin and contributors
# For license information, please see license.txt

"""MCP JSON-RPC. Stateless. Streamable HTTP clients POST one object per request.

Batch arrays are not accepted: Frappe parses the body before this module
runs and rejects a JSON array. Every current MCP client sends one message
per POST.
"""

from __future__ import annotations

import json
from urllib.parse import quote, unquote

import frappe

from frappe_mcp import __version__
from frappe_mcp.tools.registry import call_tool, mcp_tool_list

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_NAME = "frappe-mcp"

INSTRUCTIONS = (
	"You are connected to a Frappe site through the signed-in user's permissions. "
	"Read tools return only documents that user can read. Create, Read, and Update "
	"are allowed by default. Submit, Cancel, and Delete are absent unless an "
	"administrator and the connector owner both enabled them. "
	"Never invent records, field names, or numbers. Use get_schema before filters. "
	"Use resolve_date_range for relative dates. "
	"Writes require confirm=false first, then confirm=true only after the user "
	"explicitly agrees. Semantic search hits are candidates: call get_record "
	"before stating a field value. Password fields are masked."
)


def _result(msg_id, result):
	return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _error(msg_id, code, message):
	return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def handle_message(message: dict) -> dict | None:
	if not isinstance(message, dict):
		return _error(None, -32600, "Invalid request")
	method = message.get("method")
	msg_id = message.get("id")
	params = message.get("params") or {}
	if not isinstance(params, dict):
		return _error(msg_id, -32602, "Invalid params")
	if method and str(method).startswith("notifications/"):
		return None
	if msg_id is None:
		return None
	try:
		result = _dispatch(method, params)
	except frappe.ValidationError as exc:
		return _error(msg_id, -32602, str(exc))
	except Exception:
		frappe.log_error(title=f"MCP method failed: {method}")
		return _error(msg_id, -32603, "Internal error")
	if result is None:
		return _error(msg_id, -32601, f"Method not found: {method}")
	return _result(msg_id, result)


def _dispatch(method, params):
	if method == "ping":
		return {}
	if method == "initialize":
		return _initialize(params)
	if method == "tools/list":
		return {"tools": mcp_tool_list()}
	if method == "tools/call":
		return _tools_call(params)
	if method == "resources/list":
		return {"resources": _resources()}
	if method == "resources/read":
		return _resource_read(params.get("uri") or "")
	if method == "prompts/list":
		return {"prompts": _prompts()}
	if method == "prompts/get":
		return _prompt_get(params.get("name"), params.get("arguments") or {})
	if method in {"logging/setLevel", "completion/complete"}:
		return {}
	return None


def _initialize(params):
	requested = params.get("protocolVersion") or PROTOCOL_VERSIONS[0]
	version = requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
	return {
		"protocolVersion": version,
		"capabilities": {
			"tools": {"listChanged": False},
			"resources": {"subscribe": False, "listChanged": False},
			"prompts": {"listChanged": False},
		},
		"serverInfo": {"name": SERVER_NAME, "version": __version__},
		"instructions": INSTRUCTIONS,
	}


def _tools_call(params):
	import time

	from frappe_mcp.audit import log_tool_call

	name = params.get("name")
	arguments = params.get("arguments") or {}
	started = time.perf_counter()
	result = call_tool(name, arguments)
	failed = bool(result.get("error"))
	log_tool_call(
		tool_name=name or "",
		arguments=arguments,
		result=result,
		duration=time.perf_counter() - started,
		status="Error" if failed else "Success",
		doctype=(result.get("doctype") if isinstance(result, dict) else "") or arguments.get("doctype") or "",
	)
	return {
		"content": [{"type": "text", "text": json.dumps(result, default=str)}],
		"isError": failed,
	}


def _resources():
	from frappe_mcp.tools.read import list_doctypes

	try:
		rows = list_doctypes("").get("doctypes") or []
	except Exception:
		rows = []
	resources = [
		{
			"uri": "frappe://server/instructions",
			"name": "instructions",
			"description": "How this MCP server applies permissions.",
			"mimeType": "text/plain",
		}
	]
	for row in rows:
		resources.append(
			{
				"uri": "frappe://doctype/" + quote(row["doctype"]),
				"name": row["doctype"],
				"description": f"Schema for {row['doctype']}",
				"mimeType": "application/json",
			}
		)
	return resources


def _resource_read(uri: str):
	if uri == "frappe://server/instructions":
		text = INSTRUCTIONS
	elif uri.startswith("frappe://doctype/"):
		from frappe_mcp.tools.read import get_schema

		doctype = unquote(uri[len("frappe://doctype/") :])
		text = json.dumps(get_schema(doctype), default=str)
	else:
		frappe.throw(frappe._("Unknown resource {0}.").format(uri))
	return {"contents": [{"uri": uri, "mimeType": "application/json", "text": text}]}


def _prompts():
	return [
		{
			"name": "answer_question",
			"description": "Answer a business question using this user's Frappe data. Do not invent figures.",
			"arguments": [{"name": "question", "description": "The user's question", "required": True}],
		},
		{
			"name": "draft_document",
			"description": "Prepare a create_record preview. Do not confirm until the user says yes.",
			"arguments": [
				{"name": "doctype", "description": "DocType to draft", "required": True},
				{"name": "details", "description": "What the user wants on the document", "required": True},
			],
		},
		{
			"name": "explain_report",
			"description": "Run a saved report and explain the numbers, including the filters that were assumed.",
			"arguments": [{"name": "report_name", "description": "Exact report name", "required": True}],
		},
	]


def _prompt_get(name, arguments):
	arguments = arguments or {}
	if name == "answer_question":
		text = (
			"Answer this question using only tool results from this Frappe site. "
			"If a number is not in a tool result, say you do not know. Question: "
			+ str(arguments.get("question") or "")
		)
	elif name == "draft_document":
		text = (
			f"Draft a {arguments.get('doctype') or ''} document for: {arguments.get('details') or ''}. "
			"Call get_schema first. Call create_record with confirm=false. "
			"Do not pass confirm=true until the user explicitly agrees."
		)
	elif name == "explain_report":
		text = (
			f"Run the report '{arguments.get('report_name') or ''}' and explain the result. "
			"State the filters that were used. Do not invent rows."
		)
	else:
		frappe.throw(frappe._("Unknown prompt {0}.").format(name))
	return {"description": name, "messages": [{"role": "user", "content": {"type": "text", "text": text}}]}
