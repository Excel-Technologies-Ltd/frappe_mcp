# Copyright (c) 2026, Shaid Azmin and contributors
# For license information, please see license.txt

import frappe

from frappe_mcp.ai.schema import clear_schema_cache, is_indexable_doctype


def clear_schema_cache_for_doctype(doc, method=None):
	clear_schema_cache(doc.name)


def clear_schema_cache_for_custom_field(doc, method=None):
	clear_schema_cache(doc.dt)


def index_record_for_semantic_search(doc, method=None):
	if not is_indexable_doctype(doc.doctype):
		return
	from frappe_mcp.ai.embeddings import embedding_available

	if not embedding_available():
		return
	frappe.enqueue(
		"frappe_mcp.ai.semantic.index_record",
		queue="short",
		enqueue_after_commit=True,
		doctype=doc.doctype,
		name=doc.name,
	)


def remove_record_from_semantic_index(doc, method=None):
	if not is_indexable_doctype(doc.doctype):
		return
	frappe.enqueue(
		"frappe_mcp.ai.semantic.delete_record_from_index",
		queue="short",
		enqueue_after_commit=True,
		doctype=doc.doctype,
		name=doc.name,
	)
