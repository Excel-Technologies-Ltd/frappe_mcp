# Copyright (c) 2026, Shaid Azmin and contributors
# For license information, please see license.txt

"""Desk chat sessions. One user cannot read another's session."""

from __future__ import annotations

import frappe

MAX_HISTORY_MESSAGES = 10
MAX_HISTORY_MESSAGE_LENGTH = 1500
MAX_TITLE_LENGTH = 80


def _title(first_message: str) -> str:
	title = (first_message or "").strip().replace("\n", " ")
	if len(title) > MAX_TITLE_LENGTH:
		title = title[: MAX_TITLE_LENGTH - 1].rstrip() + "…"
	return title or "New chat"


def get_or_create_session(session_name: str | None, first_message: str):
	if session_name:
		session = frappe.get_doc("MCP Chat Session", session_name)
		session.check_permission("read")
		if session.owner != frappe.session.user and "System Manager" not in frappe.get_roles():
			frappe.throw(frappe._("Not permitted"), frappe.PermissionError)
		return session
	session = frappe.get_doc(
		{"doctype": "MCP Chat Session", "title": _title(first_message), "messages": []}
	)
	session.insert(ignore_permissions=True)
	return session


def append_and_save(session, query: str, answer: str) -> None:
	session.append("messages", {"role": "User", "content": str(query)[:8000]})
	session.append("messages", {"role": "Assistant", "content": str(answer)[:8000]})
	session.save(ignore_permissions=True)


def history_messages(session) -> list[dict]:
	rows = (session.get("messages") or [])[-MAX_HISTORY_MESSAGES:]
	messages = []
	for row in rows:
		content = (row.content or "").strip()[:MAX_HISTORY_MESSAGE_LENGTH]
		if not content:
			continue
		role = "assistant" if row.role == "Assistant" else "user"
		messages.append({"role": role, "content": content})
	return messages


def list_sessions() -> list[dict]:
	return frappe.get_list(
		"MCP Chat Session",
		fields=["name", "title", "modified"],
		order_by="modified desc",
		limit_page_length=50,
	)


def session_detail(session_name: str) -> dict:
	session = frappe.get_doc("MCP Chat Session", session_name)
	session.check_permission("read")
	return {
		"name": session.name,
		"title": session.title,
		"messages": [{"role": row.role, "content": row.content} for row in (session.get("messages") or [])],
	}


def delete_session(session_name: str) -> None:
	session = frappe.get_doc("MCP Chat Session", session_name)
	session.check_permission("delete")
	frappe.delete_doc("MCP Chat Session", session_name)
