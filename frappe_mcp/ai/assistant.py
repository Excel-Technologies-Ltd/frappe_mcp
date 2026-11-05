# Copyright (c) 2026, Shaid Azmin and contributors
# For license information, please see license.txt

"""Desk assistant. OpenAI-compatible tool calling against the same tools
the MCP server exposes. The model is whatever MCP Settings points at.
The principal is the logged-in user, under the site action switches.
"""

from __future__ import annotations

import json
import time

import frappe
import requests

from frappe_mcp.ai.chat import append_and_save, get_or_create_session, history_messages
from frappe_mcp.audit import log_query, log_tool_call
from frappe_mcp.policy import bind_policy, site_policy
from frappe_mcp.settings import get_settings
from frappe_mcp.tools.registry import call_tool, openai_tool_list

_MAX_ROUNDS = 8
_TIMEOUT = 90


def _require_assistant():
	if frappe.session.user in ("", "Guest"):
		frappe.throw(frappe._("Login required."), frappe.PermissionError)
	if not get_settings().get("enable_ai_assistant"):
		frappe.throw(frappe._("The AI assistant is disabled in MCP Settings."))


def _password(settings, fieldname: str) -> str | None:
	if hasattr(settings, "get_password"):
		return settings.get_password(fieldname, raise_exception=False)
	return None


def _chat_endpoint(settings):
	provider = settings.get("llm_provider") or "Ollama"
	if provider == "Ollama":
		base = (settings.get("ollama_base_url") or "").rstrip("/")
		if not base:
			frappe.throw(frappe._("Ollama Base URL is required."))
		return f"{base}/v1/chat/completions", {}, settings.get("ollama_model") or "llama3.1:8b"
	if provider == "OpenAI":
		key = _password(settings, "openai_api_key")
		if not key:
			frappe.throw(frappe._("OpenAI API Key is required."))
		return (
			"https://api.openai.com/v1/chat/completions",
			{"Authorization": f"Bearer {key}"},
			settings.get("openai_model") or "gpt-4o-mini",
		)
	base = (settings.get("compatible_base_url") or "").rstrip("/")
	if not base:
		frappe.throw(frappe._("Compatible Base URL is required."))
	if base.endswith("/chat/completions"):
		url = base
	elif base.endswith("/v1"):
		url = base + "/chat/completions"
	else:
		url = base + "/v1/chat/completions"
	key = _password(settings, "compatible_api_key")
	headers = {"Authorization": f"Bearer {key}"} if key else {}
	model = settings.get("compatible_model")
	if not model:
		frappe.throw(frappe._("Compatible model is required."))
	return url, headers, model


def _system_prompt() -> str:
	from frappe_mcp.mcp.protocol import INSTRUCTIONS
	from frappe_mcp.tools.read import whoami

	identity = whoami()
	return (
		INSTRUCTIONS
		+ " You are the in-desk assistant. Today is "
		+ str(frappe.utils.today())
		+ ". The signed-in user is "
		+ identity["user"]
		+ ". Enabled actions: "
		+ json.dumps(identity["permissions"])
		+ ". If a tool is not in your tool list, you cannot do that action. Say so."
	)


def _complete(url, headers, model, messages, tools):
	response = requests.post(
		url,
		headers={"Content-Type": "application/json", **headers},
		json={
			"model": model,
			"messages": messages,
			"tools": tools,
			"temperature": 0.1,
		},
		timeout=_TIMEOUT,
	)
	if response.status_code >= 400:
		frappe.throw(
			frappe._("The language model returned {0}: {1}").format(
				response.status_code, response.text[:500]
			)
		)
	payload = response.json()
	choices = payload.get("choices") or []
	if not choices:
		frappe.throw(frappe._("The language model returned no choices."))
	return choices[0].get("message") or {}


def ask(query: str, session_name: str | None = None) -> dict:
	_require_assistant()
	query = (query or "").strip()
	if not query:
		frappe.throw(frappe._("A question is required."))
	if len(query) > 8000:
		frappe.throw(frappe._("Question is too long."))

	bind_policy(site_policy())
	frappe.flags.mcp_source = "Assistant"
	settings = get_settings()
	url, headers, model = _chat_endpoint(settings)
	session = get_or_create_session(session_name, query)
	messages = [{"role": "system", "content": _system_prompt()}]
	messages.extend(history_messages(session))
	messages.append({"role": "user", "content": query})
	tools = openai_tool_list()
	started = time.perf_counter()
	used = []
	doctypes = []
	try:
		answer = _run_loop(url, headers, model, messages, tools, used, doctypes)
		append_and_save(session, query, answer)
		log_query(
			query=query,
			answer=answer,
			status="Success",
			duration=time.perf_counter() - started,
			tool_call_count=len(used),
			doctypes_touched=", ".join(dict.fromkeys(doctypes)),
		)
		return {"answer": answer, "session": session.name, "tool_calls": used}
	except Exception as exc:
		log_query(
			query=query,
			answer="",
			status="Error",
			duration=time.perf_counter() - started,
			tool_call_count=len(used),
			doctypes_touched=", ".join(dict.fromkeys(doctypes)),
			error=str(exc),
		)
		raise


def _run_loop(url, headers, model, messages, tools, used, doctypes) -> str:
	for _round in range(_MAX_ROUNDS):
		message = _complete(url, headers, model, messages, tools)
		tool_calls = message.get("tool_calls") or []
		if not tool_calls:
			return (message.get("content") or "").strip() or frappe._("No answer was returned.")
		messages.append(
			{
				"role": "assistant",
				"content": message.get("content") or "",
				"tool_calls": tool_calls,
			}
		)
		for call in tool_calls:
			function = call.get("function") or {}
			name = function.get("name")
			raw_args = function.get("arguments") or "{}"
			try:
				args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
			except json.JSONDecodeError:
				args = {}
			started = time.perf_counter()
			result = call_tool(name, args if isinstance(args, dict) else {})
			log_tool_call(
				tool_name=name or "",
				arguments=args if isinstance(args, dict) else {},
				result=result,
				duration=time.perf_counter() - started,
				status="Error" if result.get("error") else "Success",
				doctype=(result.get("doctype") if isinstance(result, dict) else "") or "",
			)
			used.append(name)
			if isinstance(result, dict) and result.get("doctype"):
				doctypes.append(result["doctype"])
			messages.append(
				{
					"role": "tool",
					"tool_call_id": call.get("id") or name,
					"content": json.dumps(result, default=str)[:12000],
				}
			)
	return frappe._("Stopped after too many tool calls. Narrow the question and try again.")
