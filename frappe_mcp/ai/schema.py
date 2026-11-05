# Copyright (c) 2026, Shaid Azmin and contributors
# For license information, please see license.txt

"""Live DocType discovery. No hardcoded business DocTypes.

Permission-filtered per user. Desk plumbing and this app's own documents
(connectors, tokens, logs, chats) stay out of the catalog.
"""

from __future__ import annotations

import re

import frappe
from frappe.permissions import get_doctypes_with_read

from frappe_mcp.settings import setting

CACHE_KEY_LIST = "frappe_mcp:queryable_doctypes"
CACHE_KEY_DOCTYPE = "frappe_mcp:doctype_schema:{doctype}"
CACHE_KEY_PREFIX_MAP = "frappe_mcp:name_prefix_map"

EXCLUDED_MODULES = {
	"Core",
	"Custom",
	"Email",
	"Desk",
	"Automation",
	"Workflow",
	"Printing",
	"Integrations",
	"Social",
	"Website",
	"Portal",
	"Contacts",
	"Frappe Mcp",
}
EXCLUDED_DOCTYPES = {
	"DocType",
	"DocField",
	"DocPerm",
	"Custom DocPerm",
	"Custom Field",
	"Property Setter",
	"Module Def",
	"User",
	"Role",
	"Has Role",
	"Session Default",
	"Access Log",
	"Error Log",
	"Scheduled Job Log",
	"Version",
	"Activity Log",
	"MCP Settings",
	"MCP Connector",
	"MCP Query Log",
	"MCP Tool Log",
	"MCP Chat Session",
	"MCP Chat Message",
	"DefaultValue",
	"Communication",
	"File",
}
INCLUDED_DESPITE_MODULE = {"ToDo", "Event", "Note"}

_LAYOUT_FIELDS = {"Section Break", "Column Break", "Tab Break", "HTML", "Button", "Fold"}


def _cache_ttl_seconds() -> int:
	try:
		minutes = int(setting("schema_cache_ttl_minutes", 60) or 60)
	except (TypeError, ValueError):
		minutes = 60
	return max(minutes, 1) * 60


def is_indexable_doctype(doctype: str) -> bool:
	if doctype in EXCLUDED_DOCTYPES:
		return False
	try:
		meta = frappe.get_meta(doctype)
	except Exception:
		return False
	if meta.istable or meta.issingle:
		return False
	if meta.module in EXCLUDED_MODULES and doctype not in INCLUDED_DESPITE_MODULE:
		return False
	return True


def list_queryable_doctypes(user: str | None = None) -> list[dict]:
	user = user or frappe.session.user
	cache_key = f"{CACHE_KEY_LIST}:{user}"
	cached = frappe.cache().get_value(cache_key, expires=True)
	if cached is not None:
		return cached

	readable = {
		name
		for name in get_doctypes_with_read()
		if frappe.has_permission(name, "read", user=user)
	}
	result = []
	for name in sorted(readable):
		if name in EXCLUDED_DOCTYPES:
			continue
		meta_row = frappe.db.get_value(
			"DocType",
			name,
			["module", "istable", "issingle", "is_virtual", "is_submittable", "description"],
			as_dict=True,
		)
		if not meta_row or meta_row.istable:
			continue
		if meta_row.module in EXCLUDED_MODULES and name not in INCLUDED_DESPITE_MODULE:
			continue
		result.append(
			{
				"doctype": name,
				"module": meta_row.module,
				"is_single": bool(meta_row.issingle),
				"is_virtual": bool(meta_row.is_virtual),
				"is_submittable": bool(meta_row.is_submittable),
				"description": meta_row.description,
			}
		)

	frappe.cache().set_value(cache_key, result, expires_in_sec=_cache_ttl_seconds())
	return result


def load_schema(doctype: str) -> dict:
	"""Field metadata with no permission check. Callers that talk to a user
	must go through get_doctype_schema.
	"""
	cache_key = CACHE_KEY_DOCTYPE.format(doctype=doctype)
	cached = frappe.cache().get_value(cache_key, expires=True)
	if cached is not None:
		return cached

	meta = frappe.get_meta(doctype)
	fields = []
	links = []
	children = []
	for df in meta.fields:
		if df.fieldtype in _LAYOUT_FIELDS:
			continue
		fields.append(
			{
				"fieldname": df.fieldname,
				"label": df.label,
				"fieldtype": df.fieldtype,
				"options": df.options,
				"mandatory": bool(df.reqd),
				"hidden": bool(df.hidden),
				"read_only": bool(df.read_only),
				"default": df.default,
				"description": df.description,
				"precision": df.precision,
				"allow_on_submit": bool(df.allow_on_submit),
			}
		)
		if df.fieldtype == "Link" and df.options:
			links.append({"fieldname": df.fieldname, "doctype": df.options})
		elif df.fieldtype == "Dynamic Link" and df.options:
			links.append({"fieldname": df.fieldname, "doctype_field": df.options, "dynamic": True})
		elif df.fieldtype in ("Table", "Table MultiSelect") and df.options:
			children.append(
				{
					"fieldname": df.fieldname,
					"doctype": df.options,
					"multiselect": df.fieldtype == "Table MultiSelect",
				}
			)

	schema = {
		"doctype": doctype,
		"module": meta.module,
		"is_single": bool(meta.issingle),
		"is_virtual": bool(getattr(meta, "is_virtual", 0)),
		"is_submittable": bool(meta.is_submittable),
		"title_field": meta.title_field,
		"autoname": meta.autoname,
		"fields": fields,
		"links": links,
		"children": children,
	}
	frappe.cache().set_value(cache_key, schema, expires_in_sec=_cache_ttl_seconds())
	return schema


def get_doctype_schema(doctype: str, user: str | None = None) -> dict:
	user = user or frappe.session.user
	if not frappe.has_permission(doctype, "read", user=user):
		frappe.throw(
			frappe._("You do not have permission to read {0}.").format(doctype),
			frappe.PermissionError,
		)
	return load_schema(doctype)


def _prefixes_from_pattern(pattern: str) -> list[str]:
	if not pattern:
		return []
	text = pattern.strip()
	if text.lower().startswith("format:"):
		text = text[len("format:") :]
	prefix = re.split(r"[.{#]", text, maxsplit=1)[0].strip()
	return [prefix] if len(prefix) >= 2 else []


def _candidate_prefixes(meta) -> list[str]:
	autoname = (meta.autoname or "").strip()
	lower = autoname.lower()
	if lower.startswith("naming_series:"):
		field = meta.get_field("naming_series")
		prefixes = []
		if field and field.options:
			for line in field.options.split("\n"):
				prefixes.extend(_prefixes_from_pattern(line))
		return prefixes
	if not autoname or lower in ("hash", "prompt") or lower.startswith("field:"):
		return []
	return _prefixes_from_pattern(autoname)


def _build_name_prefix_index(user: str | None = None) -> list[tuple[str, str]]:
	user = user or frappe.session.user
	cache_key = f"{CACHE_KEY_PREFIX_MAP}:{user}"
	cached = frappe.cache().get_value(cache_key, expires=True)
	if cached is not None:
		return cached

	index: list[tuple[str, str]] = []
	for row in list_queryable_doctypes(user=user):
		if row["is_single"]:
			continue
		meta = frappe.get_meta(row["doctype"])
		for prefix in _candidate_prefixes(meta):
			index.append((prefix, row["doctype"]))
	index.sort(key=lambda pair: -len(pair[0]))
	frappe.cache().set_value(cache_key, index, expires_in_sec=_cache_ttl_seconds())
	return index


def find_doctype_for_identifier(identifier: str, user: str | None = None) -> str | None:
	user = user or frappe.session.user
	identifier = (identifier or "").strip()
	if not identifier:
		return None
	for prefix, doctype in _build_name_prefix_index(user=user):
		if identifier.startswith(prefix) and frappe.db.exists(doctype, identifier):
			return doctype
	for row in list_queryable_doctypes(user=user):
		if row["is_single"]:
			continue
		if frappe.db.exists(row["doctype"], identifier):
			return row["doctype"]
	return None


def clear_schema_cache(doctype: str | None = None):
	if doctype:
		frappe.cache().delete_value(CACHE_KEY_DOCTYPE.format(doctype=doctype))
	try:
		frappe.cache().delete_keys(f"{CACHE_KEY_LIST}:*")
		frappe.cache().delete_keys(f"{CACHE_KEY_PREFIX_MAP}:*")
	except Exception:
		pass
