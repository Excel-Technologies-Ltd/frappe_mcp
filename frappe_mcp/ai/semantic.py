# Copyright (c) 2026, Shaid Azmin and contributors
# For license information, please see license.txt

"""Vector index over business DocTypes and records.

The index is a discovery layer. Search results are candidates. Callers
must re-read the document through permission-checked tools before
treating any field as fact. Hits the current user cannot read are dropped.
"""

from __future__ import annotations

import uuid

import frappe

from frappe_mcp.ai.embeddings import embed_text, embedding_available
from frappe_mcp.ai.qdrant_store import collection_name, ensure_collection, get_client
from frappe_mcp.ai.schema import get_doctype_schema, is_indexable_doctype, list_queryable_doctypes

_TEXT_FIELDTYPES = {
	"Data",
	"Small Text",
	"Text",
	"Text Editor",
	"Long Text",
	"Code",
	"Markdown Editor",
}
_MAX_TEXT_FIELDS = 6
_MAX_RECORD_CHARS = 2000
_SCORE_THRESHOLD = 0.5


def _point_id(*parts: str) -> str:
	return str(uuid.uuid5(uuid.NAMESPACE_URL, ":".join(parts)))


def _text_fields_for(doctype: str) -> list[dict]:
	schema = get_doctype_schema(doctype)
	candidates = [
		field
		for field in schema["fields"]
		if field["fieldtype"] in _TEXT_FIELDTYPES and not field.get("hidden")
	]
	title_field = schema.get("title_field")
	candidates.sort(key=lambda field: 0 if field["fieldname"] == title_field else 1)
	return candidates[:_MAX_TEXT_FIELDS]


def index_doctype_catalog(user: str | None = None) -> int:
	if not embedding_available():
		return 0
	client = get_client()
	if not client:
		return 0
	from qdrant_client.http import models as qmodels

	doctypes = list_queryable_doctypes(user=user)
	points = []
	vector_size = None
	for row in doctypes:
		schema = get_doctype_schema(row["doctype"], user=user)
		labels = ", ".join(field["label"] for field in schema["fields"][:20] if field.get("label"))
		text = f"{row['doctype']}. Module: {row['module']}. {row.get('description') or ''} Fields: {labels}".strip()
		vector = embed_text(text)
		if not vector:
			continue
		vector_size = vector_size or len(vector)
		points.append(
			qmodels.PointStruct(
				id=_point_id("doctype", row["doctype"]),
				vector=vector,
				payload={"doctype": row["doctype"], "module": row["module"]},
			)
		)
	if not points or not vector_size:
		return 0
	name = collection_name("doctypes")
	ensure_collection(client, name, vector_size)
	client.upsert(collection_name=name, points=points)
	return len(points)


def semantic_search_doctypes(query: str, user: str | None = None, limit: int = 5) -> list[dict]:
	if not embedding_available():
		return []
	client = get_client()
	if not client:
		return []
	from qdrant_client.http import models as qmodels  # noqa: F401

	vector = embed_text(query, task="search_query")
	if not vector:
		return []
	name = collection_name("doctypes")
	try:
		hits = client.query_points(
			collection_name=name, query=vector, limit=limit * 3, with_payload=True
		).points
	except Exception:
		return []
	user = user or frappe.session.user
	results = []
	for hit in hits:
		if hit.score < _SCORE_THRESHOLD:
			continue
		doctype = (hit.payload or {}).get("doctype")
		if not doctype or not frappe.has_permission(doctype, "read", user=user):
			continue
		results.append(
			{
				"doctype": doctype,
				"module": (hit.payload or {}).get("module"),
				"score": round(hit.score, 3),
			}
		)
		if len(results) >= limit:
			break
	return results


def _record_text(doctype: str, name: str) -> str | None:
	fields = _text_fields_for(doctype)
	if not fields:
		return None
	fieldnames = [field["fieldname"] for field in fields]
	row = frappe.db.get_value(doctype, name, fieldnames, as_dict=True)
	if not row:
		return None
	parts = [
		f"{field['label']}: {row[field['fieldname']]}"
		for field in fields
		if row.get(field["fieldname"])
	]
	text = "\n".join(parts).strip()
	return text[:_MAX_RECORD_CHARS] if text else None


def index_record(doctype: str, name: str) -> bool:
	if not embedding_available() or not is_indexable_doctype(doctype):
		return False
	text = _record_text(doctype, name)
	if not text:
		return False
	vector = embed_text(text)
	if not vector:
		return False
	client = get_client()
	if not client:
		return False
	from qdrant_client.http import models as qmodels

	coll = collection_name("records")
	ensure_collection(client, coll, len(vector))
	client.upsert(
		collection_name=coll,
		points=[
			qmodels.PointStruct(
				id=_point_id("record", doctype, name),
				vector=vector,
				payload={"doctype": doctype, "name": name, "snippet": text[:300]},
			)
		],
	)
	return True


def delete_record_from_index(doctype: str, name: str) -> None:
	client = get_client()
	if not client:
		return
	from qdrant_client.http import models as qmodels

	coll = collection_name("records")
	try:
		client.delete(
			collection_name=coll,
			points_selector=qmodels.PointIdsList(points=[_point_id("record", doctype, name)]),
		)
	except Exception:
		pass


def run_initial_index() -> dict:
	if not embedding_available():
		return {"ran": False, "reason": "semantic search is not configured"}
	doctype_count = index_doctype_catalog(user="Administrator")
	record_result = reindex_all_records(user="Administrator")
	return {"ran": True, "doctypes_indexed": doctype_count, **record_result}


def reindex_all_records(user: str | None = None) -> dict:
	if not embedding_available():
		return {"indexed": 0, "doctypes": {}}
	counts: dict[str, int] = {}
	total = 0
	for row in list_queryable_doctypes(user=user or "Administrator"):
		doctype = row["doctype"]
		if row.get("is_single") or row.get("is_virtual"):
			continue
		if not _text_fields_for(doctype):
			continue
		names = frappe.get_all(doctype, pluck="name", limit_page_length=0)
		indexed = 0
		for name in names:
			try:
				if index_record(doctype, name):
					indexed += 1
			except Exception:
				frappe.log_error(title=f"MCP index failed for {doctype} {name}")
		if indexed:
			counts[doctype] = indexed
			total += indexed
	return {"indexed": total, "doctypes": counts}


def semantic_search_records(
	query: str, doctype: str | None = None, user: str | None = None, limit: int = 5
) -> list[dict]:
	if not embedding_available():
		return []
	client = get_client()
	if not client:
		return []
	from qdrant_client.http import models as qmodels

	vector = embed_text(query, task="search_query")
	if not vector:
		return []
	coll = collection_name("records")
	qdrant_filter = None
	if doctype:
		qdrant_filter = qmodels.Filter(
			must=[qmodels.FieldCondition(key="doctype", match=qmodels.MatchValue(value=doctype))]
		)
	try:
		hits = client.query_points(
			collection_name=coll,
			query=vector,
			limit=max(limit, 1) * 4,
			with_payload=True,
			query_filter=qdrant_filter,
		).points
	except Exception:
		return []
	user = user or frappe.session.user
	results = []
	for hit in hits:
		if hit.score < _SCORE_THRESHOLD:
			continue
		payload = hit.payload or {}
		hit_doctype = payload.get("doctype")
		hit_name = payload.get("name")
		if not hit_doctype or not hit_name:
			continue
		if not frappe.has_permission(hit_doctype, "read", doc=hit_name, user=user):
			continue
		results.append(
			{
				"doctype": hit_doctype,
				"name": hit_name,
				"score": round(hit.score, 3),
				"snippet": payload.get("snippet", ""),
			}
		)
		if len(results) >= limit:
			break
	return results
