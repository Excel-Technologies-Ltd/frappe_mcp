# Copyright (c) 2026, Shaid Azmin and contributors
# For license information, please see license.txt

"""Writes are confirm-gated and permission-gated.

confirm=false previews and creates nothing. confirm=true performs the
action only when the connector policy allows it and frappe.has_permission
agrees. Cancel and Delete stay off unless both MCP Settings and the
connector enable them.
"""

from __future__ import annotations

import frappe

from frappe_mcp.policy import assert_action, current_policy
from frappe_mcp.tools.guards import (
	apply_values,
	assert_queryable,
	missing_required,
	parse_json_object,
	wants_confirm,
)


def _preview(action: str, doctype: str, name: str | None, values: dict, message: str) -> dict:
	out = {
		"confirmed": False,
		"action": action,
		"doctype": doctype,
		"preview": values,
		"message": message,
	}
	if name:
		out["name"] = name
	return out


def create_record(doctype: str, values_json="{}" , confirm=False) -> dict:
	schema = assert_queryable(doctype, need="create")
	if schema.get("is_single"):
		frappe.throw(frappe._("{0} is a single DocType and cannot be created.").format(doctype))
	if not frappe.has_permission(doctype, "create"):
		frappe.throw(
			frappe._("You do not have permission to create {0}.").format(doctype),
			frappe.PermissionError,
		)
	values = parse_json_object(values_json, "values_json")
	missing = missing_required(schema, values)
	if missing:
		return {
			"created": False,
			"doctype": doctype,
			"missing_required_fields": missing,
			"values_so_far": values,
			"message": "Ask for the missing required fields, then call create_record again.",
		}
	if not wants_confirm(confirm):
		return _preview(
			"create",
			doctype,
			None,
			values,
			"Nothing was created. Show this preview and call create_record again with confirm=true only after an explicit yes.",
		)
	doc = frappe.get_doc({"doctype": doctype})
	apply_values(doc, schema, values)
	doc.insert()
	return {"created": True, "doctype": doctype, "name": doc.name, "docstatus": doc.docstatus}


def update_record(doctype: str, name: str, values_json="{}", confirm=False) -> dict:
	schema = assert_queryable(doctype, need="update")
	name = (name or "").strip()
	if not name or not frappe.db.exists(doctype, name):
		return {"updated": False, "found": False, "doctype": doctype, "name": name}
	if not frappe.has_permission(doctype, "write", doc=name):
		frappe.throw(
			frappe._("You do not have permission to update {0} {1}.").format(doctype, name),
			frappe.PermissionError,
		)
	values = parse_json_object(values_json, "values_json")
	if not values:
		frappe.throw(frappe._("values_json is empty. Nothing to update."))
	if not wants_confirm(confirm):
		return _preview(
			"update",
			doctype,
			name,
			values,
			"Nothing was updated. Show this preview and call update_record again with confirm=true only after an explicit yes.",
		)
	doc = frappe.get_doc(doctype, name)
	apply_values(doc, schema, values)
	doc.save()
	return {"updated": True, "doctype": doctype, "name": doc.name, "docstatus": doc.docstatus}


def submit_document(doctype: str, name: str, confirm=False) -> dict:
	schema = assert_queryable(doctype, need="submit")
	if not schema.get("is_submittable"):
		frappe.throw(frappe._("{0} is not submittable.").format(doctype))
	if not frappe.db.exists(doctype, name):
		return {"submitted": False, "found": False, "doctype": doctype, "name": name}
	if not frappe.has_permission(doctype, "submit", doc=name):
		frappe.throw(
			frappe._("You do not have permission to submit {0} {1}.").format(doctype, name),
			frappe.PermissionError,
		)
	if not wants_confirm(confirm):
		return _preview(
			"submit",
			doctype,
			name,
			{},
			"Nothing was submitted. Call submit_document again with confirm=true only after an explicit yes.",
		)
	doc = frappe.get_doc(doctype, name)
	doc.submit()
	return {"submitted": True, "doctype": doctype, "name": doc.name, "docstatus": doc.docstatus}


def cancel_document(doctype: str, name: str, confirm=False) -> dict:
	schema = assert_queryable(doctype, need="cancel")
	if not schema.get("is_submittable"):
		frappe.throw(frappe._("{0} is not submittable, so it cannot be cancelled.").format(doctype))
	if not frappe.db.exists(doctype, name):
		return {"cancelled": False, "found": False, "doctype": doctype, "name": name}
	if not frappe.has_permission(doctype, "cancel", doc=name):
		frappe.throw(
			frappe._("You do not have permission to cancel {0} {1}.").format(doctype, name),
			frappe.PermissionError,
		)
	if not wants_confirm(confirm):
		return _preview(
			"cancel",
			doctype,
			name,
			{},
			"Nothing was cancelled. Call cancel_document again with confirm=true only after an explicit yes.",
		)
	doc = frappe.get_doc(doctype, name)
	doc.cancel()
	return {"cancelled": True, "doctype": doctype, "name": doc.name, "docstatus": doc.docstatus}


def delete_document(doctype: str, name: str, confirm=False) -> dict:
	assert_queryable(doctype, need="delete")
	if not frappe.db.exists(doctype, name):
		return {"deleted": False, "found": False, "doctype": doctype, "name": name}
	if not frappe.has_permission(doctype, "delete", doc=name):
		frappe.throw(
			frappe._("You do not have permission to delete {0} {1}.").format(doctype, name),
			frappe.PermissionError,
		)
	docstatus = frappe.db.get_value(doctype, name, "docstatus")
	if docstatus == 1:
		frappe.throw(
			frappe._("{0} {1} is submitted. Cancel it first, and only if cancel is allowed.").format(
				doctype, name
			)
		)
	if not wants_confirm(confirm):
		return _preview(
			"delete",
			doctype,
			name,
			{},
			"Nothing was deleted. Call delete_document again with confirm=true only after an explicit yes.",
		)
	frappe.delete_doc(doctype, name)
	return {"deleted": True, "doctype": doctype, "name": name}


def add_comment(doctype: str, name: str, content: str, confirm=False) -> dict:
	assert_queryable(doctype, need="create")
	if not frappe.db.exists(doctype, name):
		return {"created": False, "found": False, "doctype": doctype, "name": name}
	if not frappe.has_permission(doctype, "read", doc=name):
		frappe.throw(
			frappe._("You do not have permission to comment on {0} {1}.").format(doctype, name),
			frappe.PermissionError,
		)
	text = frappe.utils.strip_html(content or "").strip()
	if not text:
		frappe.throw(frappe._("Comment content is empty."))
	text = text[:5000]
	if not wants_confirm(confirm):
		return _preview(
			"comment",
			doctype,
			name,
			{"content": text},
			"No comment was added. Call add_comment again with confirm=true after an explicit yes.",
		)
	comment = frappe.get_doc(
		{
			"doctype": "Comment",
			"comment_type": "Comment",
			"reference_doctype": doctype,
			"reference_name": name,
			"content": text,
		}
	)
	comment.insert(ignore_permissions=True)
	return {"created": True, "doctype": doctype, "name": name, "comment": comment.name}


def get_workflow(doctype: str, name: str) -> dict:
	schema = assert_queryable(doctype)
	if not frappe.db.exists(doctype, name):
		return {"found": False, "doctype": doctype, "name": name}
	if not frappe.has_permission(doctype, "read", doc=name):
		frappe.throw(frappe._("You do not have permission to read {0} {1}.").format(doctype, name), frappe.PermissionError)
	try:
		from frappe.model.workflow import get_transitions, get_workflow
	except Exception:
		return {"doctype": doctype, "name": name, "workflow": None}
	try:
		workflow = get_workflow(doctype)
	except Exception:
		return {"doctype": doctype, "name": name, "workflow": None, "is_submittable": schema["is_submittable"]}
	doc = frappe.get_doc(doctype, name)
	try:
		transitions = get_transitions(doc)
	except Exception as exc:
		return {
			"doctype": doctype,
			"name": name,
			"workflow": workflow.name,
			"state": doc.get(workflow.workflow_state_field),
			"error": str(exc),
		}
	policy = current_policy()
	actions = []
	for transition in transitions:
		next_status = frappe.db.get_value(
			"Workflow Document State",
			{"parent": workflow.name, "state": transition.get("next_state")},
			"doc_status",
		)
		blocked = None
		if str(next_status) == "1" and not policy.get("allow_submit"):
			blocked = "submit is disabled for this connector"
		if str(next_status) == "2" and not policy.get("allow_cancel"):
			blocked = "cancel is disabled for this connector"
		actions.append(
			{
				"action": transition.get("action"),
				"next_state": transition.get("next_state"),
				"next_docstatus": next_status,
				"allowed": not blocked,
				"blocked_reason": blocked,
			}
		)
	return {
		"doctype": doctype,
		"name": name,
		"workflow": workflow.name,
		"state": doc.get(workflow.workflow_state_field),
		"actions": actions,
	}


def apply_workflow_action(doctype: str, name: str, action: str, confirm=False) -> dict:
	assert_queryable(doctype, need="update")
	info = get_workflow(doctype, name)
	match = None
	for row in info.get("actions") or []:
		if row.get("action") == action:
			match = row
			break
	if not match:
		frappe.throw(frappe._("'{0}' is not an available workflow action.").format(action))
	if not match.get("allowed"):
		frappe.throw(frappe._(match.get("blocked_reason") or "This workflow action is not allowed."))
	if not wants_confirm(confirm):
		return _preview(
			"workflow",
			doctype,
			name,
			{"action": action, "next_state": match.get("next_state")},
			"No workflow action was applied. Call apply_workflow_action again with confirm=true after an explicit yes.",
		)
	from frappe.model.workflow import apply_workflow

	doc = frappe.get_doc(doctype, name)
	apply_workflow(doc, action)
	doc.reload()
	return {
		"applied": True,
		"doctype": doctype,
		"name": doc.name,
		"action": action,
		"state": doc.get(frappe.model.workflow.get_workflow(doctype).workflow_state_field),
		"docstatus": doc.docstatus,
	}
