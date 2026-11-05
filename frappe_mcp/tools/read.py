# Copyright (c) 2026, Shaid Azmin and contributors
# For license information, please see license.txt

"""Read tools. Every list goes through frappe.get_list so user permissions,
if_owner, and user permissions apply. frappe.get_all is never used here.
"""

from __future__ import annotations

import frappe

from frappe_mcp.ai.schema import find_doctype_for_identifier, list_queryable_doctypes
from frappe_mcp.policy import assert_action
from frappe_mcp.tools.guards import (
	HIGH_VALUE_FIELDTYPES,
	SCHEMA_FIELD_CAP,
	assert_not_single,
	assert_queryable,
	child_schema,
	clamp_limit,
	default_list_fields,
	parse_fields,
	parse_filters,
	parse_order_by,
	ranked_fields,
	redact_record,
	resolve_date_phrase,
	valid_fieldnames,
)


def resolve_date_range(phrase: str) -> dict:
	assert_action("read")
	start, end = resolve_date_phrase(phrase)
	return {"phrase": phrase, "from_date": str(start), "to_date": str(end)}


def whoami() -> dict:
	from frappe_mcp.policy import current_policy

	user = frappe.session.user
	policy = current_policy()
	return {
		"user": user,
		"full_name": frappe.utils.get_fullname(user),
		"roles": frappe.get_roles(user),
		"connector": policy.get("connector"),
		"source": policy.get("source"),
		"permissions": {
			"read": bool(policy.get("allow_read", True)),
			"create": bool(policy.get("allow_create", True)),
			"update": bool(policy.get("allow_update", True)),
			"submit": bool(policy.get("allow_submit")),
			"cancel": bool(policy.get("allow_cancel")),
			"delete": bool(policy.get("allow_delete")),
		},
		"reports_enabled": bool(policy.get("reports")),
		"semantic_search_enabled": bool(policy.get("semantic")),
		"allowed_doctypes": policy.get("allowed_doctypes") or [],
		"blocked_doctypes": policy.get("blocked_doctypes") or [],
		"today": str(frappe.utils.today()),
	}


def list_doctypes(search: str = "") -> dict:
	assert_action("read")
	rows = list_queryable_doctypes()
	from frappe_mcp.policy import doctype_in_scope

	rows = [row for row in rows if doctype_in_scope(row["doctype"])]
	if search:
		needle = search.lower()
		rows = [
			row
			for row in rows
			if needle in row["doctype"].lower() or needle in (row.get("module") or "").lower()
		]
	preview = rows[:30]
	out = {
		"doctypes": [
			{
				"doctype": row["doctype"],
				"module": row["module"],
				"is_submittable": row["is_submittable"],
				"description": row.get("description"),
			}
			for row in preview
		]
	}
	if len(rows) > 30:
		out["note"] = f"Showing 30 of {len(rows)}. Pass search to narrow."
	return out


def get_schema(doctype: str, search: str = "") -> dict:
	schema = assert_queryable(doctype)
	fields = schema["fields"]
	truncated = False
	if search:
		needle = search.lower()
		fields = [
			field
			for field in fields
			if needle in (field["fieldname"] or "").lower() or needle in (field["label"] or "").lower()
		]
	else:
		high = [field for field in fields if field["fieldtype"] in HIGH_VALUE_FIELDTYPES]
		rest = [field for field in fields if field["fieldtype"] not in HIGH_VALUE_FIELDTYPES]
		ordered = high + rest
		truncated = len(ordered) > SCHEMA_FIELD_CAP
		fields = ordered[:SCHEMA_FIELD_CAP]
	result = {
		"doctype": schema["doctype"],
		"module": schema["module"],
		"is_submittable": schema["is_submittable"],
		"is_single": schema["is_single"],
		"title_field": schema.get("title_field"),
		"fields": [
			{
				"fieldname": field["fieldname"],
				"label": field["label"],
				"fieldtype": field["fieldtype"],
				"options": field["options"],
				"mandatory": field["mandatory"],
			}
			for field in fields
		],
		"links": schema["links"],
		"children": schema["children"],
	}
	if truncated:
		result["note"] = (
			f"Showing {len(fields)} of {len(schema['fields'])} fields. Pass search to find one field."
		)
	return result


def get_permissions(doctype: str) -> dict:
	schema = assert_queryable(doctype)
	user = frappe.session.user
	policy = frappe.flags.get("mcp_policy") or {}
	kinds = ("read", "create", "write", "submit", "cancel", "delete", "report")
	frappe_perms = {kind: bool(frappe.has_permission(doctype, kind, user=user)) for kind in kinds}
	return {
		"doctype": doctype,
		"is_submittable": schema["is_submittable"],
		"frappe_permissions": frappe_perms,
		"connector_permissions": {
			"read": bool(policy.get("allow_read")),
			"create": bool(policy.get("allow_create")),
			"update": bool(policy.get("allow_update")) and frappe_perms["write"],
			"submit": bool(policy.get("allow_submit")) and frappe_perms["submit"],
			"cancel": bool(policy.get("allow_cancel")) and frappe_perms["cancel"],
			"delete": bool(policy.get("allow_delete")) and frappe_perms["delete"],
		},
	}


def _resolve_record(identifier: str, doctype: str = "") -> tuple[str, str]:
	identifier = (identifier or "").strip()
	if not identifier:
		frappe.throw(frappe._("A record id is required."))
	if doctype:
		assert_queryable(doctype)
		if not frappe.db.exists(doctype, identifier):
			return doctype, ""
		return doctype, identifier
	resolved = find_doctype_for_identifier(identifier)
	if not resolved:
		return "", ""
	return resolved, identifier


def get_record(identifier: str, doctype: str = "") -> dict:
	doctype, name = _resolve_record(identifier, doctype)
	if not doctype or not name:
		return {
			"found": False,
			"identifier": identifier,
			"message": "No readable record with that id was found.",
		}
	schema = assert_queryable(doctype)
	if not schema.get("is_single") and not frappe.has_permission(doctype, "read", doc=name):
		frappe.throw(
			frappe._("You do not have permission to read {0} {1}.").format(doctype, name),
			frappe.PermissionError,
		)
	if schema.get("is_single"):
		doc = frappe.get_doc(doctype)
		data = redact_record(doc.as_dict(), schema)
		return {"found": True, "doctype": doctype, "record": data}
	fieldnames = list(dict.fromkeys(["name"] + [field["fieldname"] for field in ranked_fields(schema)]))
	row = frappe.db.get_value(doctype, name, fieldnames, as_dict=True)
	if not row:
		return {"found": False, "identifier": identifier, "doctype": doctype}
	row = redact_record(dict(row), schema)
	row = {key: value for key, value in row.items() if value not in (None, "") or key == "name"}
	out = {"found": True, "doctype": doctype, "record": row}
	if schema["children"]:
		out["child_tables"] = [child["doctype"] for child in schema["children"]]
	return out


def get_child_records(parent_identifier: str, child_doctype: str = "", parent_doctype: str = "") -> dict:
	parent_doctype, parent_name = _resolve_record(parent_identifier, parent_doctype)
	if not parent_doctype or not parent_name:
		return {"found": False, "identifier": parent_identifier, "message": "Parent record was not found."}
	schema = assert_queryable(parent_doctype)
	if not frappe.has_permission(parent_doctype, "read", doc=parent_name):
		frappe.throw(
			frappe._("You do not have permission to read {0} {1}.").format(parent_doctype, parent_name),
			frappe.PermissionError,
		)
	children = schema["children"]
	if not children:
		return {"found": True, "parent_doctype": parent_doctype, "parent": parent_name, "child_tables": []}
	if child_doctype:
		matches = [child for child in children if child["doctype"] == child_doctype]
		if not matches:
			frappe.throw(
				frappe._("'{0}' is not a child table of {1}. Choices: {2}.").format(
					child_doctype, parent_doctype, ", ".join(child["doctype"] for child in children)
				)
			)
		chosen = matches[0]
	elif len(children) == 1:
		chosen = children[0]
	else:
		return {
			"found": True,
			"parent_doctype": parent_doctype,
			"parent": parent_name,
			"message": "This parent has more than one child table. Pass child_doctype.",
			"child_tables": [child["doctype"] for child in children],
		}
	child = child_schema(chosen["doctype"])
	fieldnames = list(
		dict.fromkeys(["name", "idx"] + [field["fieldname"] for field in ranked_fields(child)])
	)
	limit = max_rows_plus_one()
	rows = frappe.get_list(
		chosen["doctype"],
		filters={"parent": parent_name, "parenttype": parent_doctype, "parentfield": chosen["fieldname"]},
		fields=fieldnames,
		order_by="idx asc",
		limit_page_length=limit,
		parent_doctype=parent_doctype,
	)
	truncated = len(rows) > max_result()
	rows = [redact_record(dict(row), child) for row in rows[: max_result()]]
	out = {
		"found": True,
		"parent_doctype": parent_doctype,
		"parent": parent_name,
		"child_doctype": chosen["doctype"],
		"doctype": chosen["doctype"],
		"records": rows,
	}
	if truncated:
		out["note"] = f"Showing the first {max_result()} rows."
	return out


def max_result():
	from frappe_mcp.tools.guards import max_result_rows

	return max_result_rows()


def max_rows_plus_one():
	return max_result() + 1


def count_records(doctype: str, filters_json="{}" ) -> dict:
	schema = assert_queryable(doctype)
	assert_not_single(doctype, schema)
	filters = parse_filters(doctype, schema, filters_json)
	rows = frappe.get_list(doctype, filters=filters, fields=["count(name) as result"])
	count = rows[0].result if rows else 0
	return {"doctype": doctype, "filters": filters, "count": count}


def query_records(
	doctype: str, filters_json="{}", fields_json="[]", limit: int = 20, order_by: str = ""
) -> dict:
	schema = assert_queryable(doctype)
	assert_not_single(doctype, schema)
	filters = parse_filters(doctype, schema, filters_json)
	fields = parse_fields(fields_json, schema) or default_list_fields(schema)
	safe_limit = clamp_limit(limit)
	order = parse_order_by(order_by, schema)
	rows = frappe.get_list(
		doctype,
		filters=filters,
		fields=fields,
		limit_page_length=safe_limit,
		order_by=order,
	)
	records = [redact_record(dict(row), schema) for row in rows]
	return {
		"doctype": doctype,
		"filters": filters,
		"count_returned": len(records),
		"row_limit": safe_limit,
		"records": records,
	}


def aggregate_field(doctype: str, fieldname: str, operation: str = "sum", filters_json="{}") -> dict:
	from frappe_mcp.tools.guards import SAFE_AGGREGATIONS

	schema = assert_queryable(doctype)
	assert_not_single(doctype, schema)
	filters = parse_filters(doctype, schema, filters_json)
	operation = (operation or "sum").lower()
	if operation not in SAFE_AGGREGATIONS:
		frappe.throw(frappe._("operation must be one of: {0}.").format(", ".join(sorted(SAFE_AGGREGATIONS))))
	if operation != "count" and fieldname not in valid_fieldnames(schema):
		frappe.throw(frappe._("'{0}' is not a field on {1}.").format(fieldname, doctype))
	if operation == "count":
		expression = "count(name) as result"
	else:
		expression = f"{operation}(`{fieldname}`) as result"
	rows = frappe.get_list(doctype, filters=filters, fields=[expression])
	result = rows[0]["result"] if rows and rows[0].get("result") is not None else 0
	return {
		"doctype": doctype,
		"operation": operation,
		"fieldname": fieldname,
		"filters": filters,
		"result": result,
	}


def search_link(doctype: str, text: str, limit: int = 20) -> dict:
	assert_queryable(doctype)
	from frappe.desk.search import search_link as _search_link

	page_length = clamp_limit(limit, default=10)
	_search_link(doctype, text or "", page_length=page_length)
	results = frappe.response.get("results") or []
	return {"doctype": doctype, "text": text, "matches": results[:page_length]}


def get_comments(doctype: str, name: str, limit: int = 20) -> dict:
	schema = assert_queryable(doctype)
	if not schema.get("is_single") and not frappe.has_permission(doctype, "read", doc=name):
		frappe.throw(frappe._("You do not have permission to read {0} {1}.").format(doctype, name), frappe.PermissionError)
	rows = frappe.get_list(
		"Comment",
		filters={"reference_doctype": doctype, "reference_name": name, "comment_type": "Comment"},
		fields=["name", "content", "owner", "creation"],
		order_by="creation desc",
		limit_page_length=clamp_limit(limit),
	)
	return {"doctype": doctype, "name": name, "comments": rows}


def get_attachments(doctype: str, name: str) -> dict:
	assert_queryable(doctype)
	if not frappe.has_permission(doctype, "read", doc=name):
		frappe.throw(frappe._("You do not have permission to read {0} {1}.").format(doctype, name), frappe.PermissionError)
	rows = frappe.get_list(
		"File",
		filters={"attached_to_doctype": doctype, "attached_to_name": name},
		fields=["name", "file_name", "file_url", "is_private", "file_size"],
		limit_page_length=50,
	)
	return {
		"doctype": doctype,
		"name": name,
		"files": rows,
		"note": "Private file bytes are not returned. Open private files from the desk while logged in as this user.",
	}


def get_linked_documents(doctype: str, name: str) -> dict:
	assert_queryable(doctype)
	from frappe.desk.form.linked_with import get as linked_get

	raw = linked_get(doctype, name) or {}
	trimmed = {}
	for linked_doctype, rows in raw.items():
		if not isinstance(rows, list):
			continue
		trimmed[linked_doctype] = rows[:20]
		if len(rows) > 20:
			trimmed[linked_doctype + "__note"] = f"{len(rows)} linked rows, showing 20."
	return {"doctype": doctype, "name": name, "links": trimmed}
