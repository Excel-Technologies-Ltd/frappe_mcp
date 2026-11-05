# Copyright (c) 2026, Shaid Azmin and contributors
# For license information, please see license.txt

import frappe


def _manager():
	if frappe.session.user != "Administrator" and "System Manager" not in frappe.get_roles():
		frappe.throw(frappe._("Only a System Manager can do this."), frappe.PermissionError)


@frappe.whitelist()
def reindex_semantic_search():
	_manager()
	frappe.enqueue("frappe_mcp.ai.semantic.run_initial_index", queue="long")
	return {"queued": True}


@frappe.whitelist()
def reset_vector_index():
	_manager()
	from frappe_mcp.ai.qdrant_store import collection_name, get_client

	client = get_client()
	if not client:
		frappe.throw(frappe._("Qdrant is not configured."))
	for kind in ("doctypes", "records"):
		name = collection_name(kind)
		try:
			client.delete_collection(name)
		except Exception:
			pass
	frappe.enqueue("frappe_mcp.ai.semantic.run_initial_index", queue="long")
	return {"reset": True, "queued": True}


@frappe.whitelist()
def test_embedding():
	_manager()
	from frappe_mcp.ai.embeddings import embed_text, embedding_available

	if not embedding_available():
		frappe.throw(
			frappe._(
				"Semantic search is not fully configured. Enable Semantic Search, enable Qdrant, set the Qdrant URL, and set an Embedding Model."
			)
		)
	vector = embed_text("frappe mcp connection test", task="search_query")
	if not vector:
		frappe.throw(frappe._("The embedding endpoint returned an empty vector."))
	return {"ok": True, "dimensions": len(vector)}
