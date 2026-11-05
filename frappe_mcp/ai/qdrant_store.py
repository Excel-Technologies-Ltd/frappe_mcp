# Copyright (c) 2026, Shaid Azmin and contributors
# For license information, please see license.txt

"""Qdrant client. Import stays inside functions so the app still boots
when the optional client is not installed.
"""

from __future__ import annotations

import frappe

from frappe_mcp.settings import get_settings


def get_client():
	settings = get_settings()
	if not settings.get("qdrant_enabled") or not settings.get("qdrant_url"):
		return None
	try:
		from qdrant_client import QdrantClient
	except ImportError:
		return None
	api_key = None
	if hasattr(settings, "get_password"):
		api_key = settings.get_password("qdrant_api_key", raise_exception=False)
	return QdrantClient(url=settings.get("qdrant_url"), api_key=api_key or None, timeout=15)


def collection_name(kind: str) -> str:
	settings = get_settings()
	prefix = settings.get("qdrant_collection_prefix") or frappe.scrub(getattr(frappe.local, "site", None) or "default")
	prefix = frappe.scrub(prefix) or "site"
	return f"{prefix}_{kind}"


def _vector_size(info) -> int | None:
	vectors = getattr(getattr(info, "config", None), "params", None)
	vectors = getattr(vectors, "vectors", None)
	if vectors is None:
		return None
	size = getattr(vectors, "size", None)
	if isinstance(size, int):
		return size
	if isinstance(vectors, dict):
		first = next(iter(vectors.values()), None)
		return getattr(first, "size", None)
	return None


def ensure_collection(client, name: str, vector_size: int) -> None:
	from qdrant_client.http import models as qmodels

	existing = {c.name for c in client.get_collections().collections}
	if name in existing:
		info = client.get_collection(name)
		current = _vector_size(info)
		if current and current != vector_size:
			frappe.throw(
				frappe._(
					"Qdrant collection {0} was built with dimension {1} but the embedding model returned {2}. "
					"Use Reset Vector Index on MCP Settings after changing the embedding model."
				).format(name, current, vector_size)
			)
		return
	client.create_collection(
		collection_name=name,
		vectors_config=qmodels.VectorParams(size=vector_size, distance=qmodels.Distance.COSINE),
	)
