# Copyright (c) 2026, Shaid Azmin and contributors
# For license information, please see license.txt

"""Shared validation for every tool. Field names and operators are
allow-listed before they reach the query builder. Password-like values
never leave a tool response.
"""

from __future__ import annotations

import calendar
import json
import re
from datetime import date, timedelta

import frappe

from frappe_mcp.ai.schema import get_doctype_schema, list_queryable_doctypes, load_schema
from frappe_mcp.policy import assert_action, doctype_in_scope
from frappe_mcp.settings import as_bool, setting

SAFE_OPERATORS = {"=", "!=", ">", "<", ">=", "<=", "like", "not like", "in", "not in", "between", "is"}
SAFE_AGGREGATIONS = {"sum", "avg", "min", "max", "count"}
NON_SELECTABLE = {"Table", "Table MultiSelect"}
HIGH_VALUE_FIELDTYPES = {
	"Date",
	"Datetime",
	"Time",
	"Currency",
	"Int",
	"Float",
	"Percent",
	"Select",
	"Check",
	"Link",
	"Dynamic Link",
	"Table",
	"Table MultiSelect",
	"Data",
}
SENSITIVE_FIELDTYPES = {"Password"}
SENSITIVE_NAMES = {
	"password",
	"new_password",
	"api_secret",
	"api_key",
	"secret",
	"token",
	"access_token",
	"refresh_token",
	"token_hash",
	"authorization",
	"pwd",
}
SYSTEM_WRITE_FIELDS = {
	"name",
	"owner",
	"creation",
	"modified",
	"modified_by",
	"docstatus",
	"idx",
	"parent",
	"parenttype",
	"parentfield",
	"doctype",
}
_FIELD_RE = re.compile(r"^[A-Za-z0-9_]+$")
_DOCTYPE_RE = re.compile(r"^[\w][\w \-./&()]{0,139}$", re.UNICODE)
SCHEMA_FIELD_CAP = 40


def max_result_rows() -> int:
	try:
		return max(int(setting("max_result_rows", 500) or 500), 1)
	except (TypeError, ValueError):
		return 500


def resolve_date_phrase(phrase: str) -> tuple[date, date]:
	today = frappe.utils.getdate(frappe.utils.today())
	text = (phrase or "").strip().lower()
	if text in ("today",):
		return today, today
	if text in ("yesterday",):
		day = today - timedelta(days=1)
		return day, day
	if text in ("tomorrow",):
		day = today + timedelta(days=1)
		return day, day
	if text in ("this week",):
		start = today - timedelta(days=today.weekday())
		return start, start + timedelta(days=6)
	if text in ("last week",):
		this_start = today - timedelta(days=today.weekday())
		start = this_start - timedelta(days=7)
		return start, start + timedelta(days=6)
	if text in ("this month",):
		return today.replace(day=1), date(
			today.year, today.month, calendar.monthrange(today.year, today.month)[1]
		)
	if text in ("last month",):
		first = today.replace(day=1)
		last_prev = first - timedelta(days=1)
		return last_prev.replace(day=1), last_prev
	if text in ("this quarter",):
		return _quarter_bounds(today)
	if text in ("last quarter",):
		this_start, _end = _quarter_bounds(today)
		return _quarter_bounds(this_start - timedelta(days=1))
	if text in ("this year",):
		return date(today.year, 1, 1), date(today.year, 12, 31)
	if text in ("last year",):
		return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)
	if text in ("year to date", "ytd", "this year to date"):
		return date(today.year, 1, 1), today
	match = re.match(r"^last (\d+) days?$", text)
	if match:
		count = int(match.group(1))
		return today - timedelta(days=count - 1 if count > 0 else 0), today
	match = re.match(r"^last (\d+) weeks?$", text)
	if match:
		return today - timedelta(weeks=int(match.group(1))), today
	match = re.match(r"^last (\d+) months?$", text)
	if match:
		count = int(match.group(1))
		year = today.year
		month = today.month - count
		while month < 1:
			month += 12
			year -= 1
		return date(year, month, 1), today
	frappe.throw(
		frappe._(
			"'{0}' is not a recognized date phrase. Try today, yesterday, this week, "
			"last week, this month, last month, this quarter, last quarter, this year, "
			"last year, year to date, last N days, last N weeks, or last N months."
		).format(phrase)
	)


def _quarter_bounds(day: date) -> tuple[date, date]:
	start_month = (day.month - 1) // 3 * 3 + 1
	end_month = start_month + 2
	start = date(day.year, start_month, 1)
	end = date(day.year, end_month, calendar.monthrange(day.year, end_month)[1])
	return start, end


def assert_doctype_name(doctype: str) -> str:
	doctype = (doctype or "").strip()
	if not doctype or not _DOCTYPE_RE.match(doctype):
		frappe.throw(frappe._("'{0}' is not a valid DocType name.").format(doctype))
	return doctype


def assert_queryable(doctype: str, *, need: str = "read") -> dict:
	doctype = assert_doctype_name(doctype)
	assert_action(need)
	if not doctype_in_scope(doctype):
		frappe.throw(
			frappe._("'{0}' is outside this connector's DocType allow list.").format(doctype)
		)
	names = {row["doctype"] for row in list_queryable_doctypes()}
	if doctype not in names:
		frappe.throw(
			frappe._(
				"'{0}' is not a DocType you can read, or it is hidden from MCP. Use list_doctypes."
			).format(doctype)
		)
	return get_doctype_schema(doctype)


def assert_not_single(doctype: str, schema: dict) -> None:
	if schema.get("is_single"):
		frappe.throw(
			frappe._("'{0}' is a settings DocType. Use get_record, not a list query.").format(doctype)
		)


def is_sensitive(fieldname: str, fieldtype: str | None = None) -> bool:
	if fieldtype in SENSITIVE_FIELDTYPES:
		return True
	return (fieldname or "").lower() in SENSITIVE_NAMES


def redact_record(record: dict, schema: dict | None = None) -> dict:
	types = {}
	if schema:
		types = {field["fieldname"]: field["fieldtype"] for field in schema.get("fields") or []}
	clean = {}
	for key, value in (record or {}).items():
		if is_sensitive(key, types.get(key)):
			if value not in (None, ""):
				clean[key] = "***"
			continue
		clean[key] = value
	return clean


def valid_fieldnames(schema: dict) -> set[str]:
	names = {
		field["fieldname"]
		for field in schema["fields"]
		if field["fieldtype"] not in NON_SELECTABLE and _FIELD_RE.match(field["fieldname"] or "")
	}
	names.update({"name", "owner", "creation", "modified", "docstatus"})
	return names


def writable_fieldnames(schema: dict) -> set[str]:
	names = set()
	for field in schema["fields"]:
		fieldname = field["fieldname"] or ""
		if fieldname in SYSTEM_WRITE_FIELDS or not _FIELD_RE.match(fieldname):
			continue
		if is_sensitive(fieldname, field["fieldtype"]):
			continue
		if field["fieldtype"] in {"Table", "Table MultiSelect", "Read Only", "HTML", "Button"}:
			if field["fieldtype"] in {"Table", "Table MultiSelect"}:
				names.add(fieldname)
			continue
		names.add(fieldname)
	return names


def parse_json_object(raw, label: str) -> dict:
	if raw in (None, "", {}):
		return {}
	if isinstance(raw, dict):
		return raw
	try:
		parsed = json.loads(raw)
	except (json.JSONDecodeError, TypeError):
		frappe.throw(frappe._("{0} must be a JSON object.").format(label))
	if not isinstance(parsed, dict):
		frappe.throw(frappe._("{0} must be a JSON object.").format(label))
	return parsed


def parse_filters(doctype: str, schema: dict, filters_json) -> dict:
	filters = parse_json_object(filters_json, "filters_json")
	valid = valid_fieldnames(schema)
	for fieldname, condition in filters.items():
		if fieldname not in valid or not _FIELD_RE.match(str(fieldname)):
			frappe.throw(frappe._("'{0}' is not a field on {1}.").format(fieldname, doctype))
		if isinstance(condition, list) and len(condition) == 2:
			operator = str(condition[0]).lower()
			if operator not in SAFE_OPERATORS:
				frappe.throw(frappe._("'{0}' is not an allowed filter operator.").format(condition[0]))
	return filters


def parse_order_by(order_by: str, schema: dict) -> str | None:
	if not order_by or not str(order_by).strip():
		return None
	parts = str(order_by).strip().split()
	if len(parts) > 2:
		frappe.throw(frappe._("order_by must be one field, optionally followed by asc or desc."))
	fieldname = parts[0]
	direction = parts[1].lower() if len(parts) == 2 else "asc"
	if fieldname not in valid_fieldnames(schema) or direction not in {"asc", "desc"}:
		frappe.throw(frappe._("'{0}' is not a valid order_by.").format(order_by))
	return f"`{fieldname}` {direction}"


def clamp_limit(limit, default: int = 20) -> int:
	try:
		value = int(limit if limit not in (None, "") else default)
	except (TypeError, ValueError):
		value = default
	return max(1, min(value, max_result_rows()))


def parse_fields(fields_json, schema: dict) -> list[str]:
	if fields_json in (None, "", []):
		fields = []
	elif isinstance(fields_json, list):
		fields = fields_json
	else:
		try:
			fields = json.loads(fields_json)
		except (json.JSONDecodeError, TypeError):
			frappe.throw(frappe._("fields_json must be a JSON list of fieldnames."))
	if not isinstance(fields, list):
		frappe.throw(frappe._("fields_json must be a JSON list of fieldnames."))
	valid = valid_fieldnames(schema)
	for field in fields:
		if field not in valid:
			frappe.throw(frappe._("'{0}' is not a field on this DocType.").format(field))
	return fields[:SCHEMA_FIELD_CAP]


def default_list_fields(schema: dict) -> list[str]:
	fields = ["name"]
	title = schema.get("title_field")
	if title and title in valid_fieldnames(schema):
		fields.append(title)
	return fields


def ranked_fields(schema: dict, cap: int = SCHEMA_FIELD_CAP) -> list[dict]:
	selectable = [field for field in schema["fields"] if field["fieldtype"] not in NON_SELECTABLE]
	high = [field for field in selectable if field["fieldtype"] in HIGH_VALUE_FIELDTYPES]
	rest = [field for field in selectable if field["fieldtype"] not in HIGH_VALUE_FIELDTYPES]
	return (high + rest)[:cap]


def child_schema(child_doctype: str) -> dict:
	"""Child tables often have no standalone read permission. The parent
	was already authorized by the caller.
	"""
	return load_schema(child_doctype)


def apply_values(doc, schema: dict, values: dict) -> None:
	writable = writable_fieldnames(schema)
	for fieldname, value in values.items():
		if fieldname not in writable:
			frappe.throw(frappe._("'{0}' cannot be set on {1}.").format(fieldname, schema["doctype"]))
		field = next(item for item in schema["fields"] if item["fieldname"] == fieldname)
		if field["fieldtype"] in {"Table", "Table MultiSelect"}:
			if not isinstance(value, list):
				frappe.throw(frappe._("'{0}' must be a list of row objects.").format(fieldname))
			child = child_schema(field["options"])
			child_writable = writable_fieldnames(child)
			rows = []
			for row in value:
				if not isinstance(row, dict):
					frappe.throw(frappe._("Each child row must be an object."))
				clean = {}
				for key, cell in row.items():
					if key in SYSTEM_WRITE_FIELDS:
						continue
					if key not in child_writable:
						frappe.throw(
							frappe._("'{0}' is not a field on child table {1}.").format(key, field["options"])
						)
					clean[key] = cell
				rows.append(clean)
			doc.set(fieldname, rows)
			continue
		doc.set(fieldname, value)


def missing_required(schema: dict, values: dict) -> list[dict]:
	missing = []
	for field in schema["fields"]:
		if not field.get("mandatory") or field.get("default"):
			continue
		if field["fieldname"] in values and values[field["fieldname"]] not in (None, ""):
			continue
		if field["fieldtype"] in NON_SELECTABLE:
			continue
		missing.append(
			{
				"fieldname": field["fieldname"],
				"label": field["label"],
				"fieldtype": field["fieldtype"],
				"options": field["options"],
			}
		)
	return missing


def wants_confirm(confirm) -> bool:
	return as_bool(confirm)


def apply_query_timeout() -> None:
	try:
		seconds = int(setting("query_timeout_seconds", 30) or 30)
	except (TypeError, ValueError):
		seconds = 30
	seconds = max(1, min(seconds, 300))
	try:
		frappe.db.sql(f"SET SESSION max_statement_time = {seconds}")
		frappe.flags.mcp_timeout_applied = True
	except Exception:
		frappe.flags.mcp_timeout_applied = False


def clear_query_timeout() -> None:
	if not getattr(frappe.flags, "mcp_timeout_applied", False):
		return
	try:
		frappe.db.sql("SET SESSION max_statement_time = 0")
	except Exception:
		pass
	frappe.flags.mcp_timeout_applied = False
