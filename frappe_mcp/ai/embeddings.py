# Copyright (c) 2026, Shaid Azmin and contributors
# For license information, please see license.txt

"""One embedding call. Plain HTTP, no torch. Provider comes from MCP Settings."""

from __future__ import annotations

import frappe
import requests

from frappe_mcp.settings import get_settings

_TIMEOUT_SECONDS = 30


def _apply_task_prefix(text: str, model: str | None, task: str) -> str:
	if model and "nomic" in model.lower():
		prefix = "search_query: " if task == "search_query" else "search_document: "
		return f"{prefix}{text}"
	return text


def embedding_provider(settings=None) -> str:
	settings = settings if settings is not None else get_settings()
	provider = (settings.get("embedding_provider") or "Follow LLM").strip()
	if provider == "Follow LLM":
		provider = settings.get("llm_provider") or "Ollama"
	return provider


def _password(settings, fieldname: str) -> str | None:
	if hasattr(settings, "get_password"):
		return settings.get_password(fieldname, raise_exception=False)
	try:
		from frappe.utils.password import get_decrypted_password

		return get_decrypted_password("MCP Settings", "MCP Settings", fieldname, raise_exception=False)
	except Exception:
		return None


def _embedding_endpoint(settings):
	"""(url, headers, style) or None when the provider is not configured."""
	provider = embedding_provider(settings)
	model = (settings.get("embedding_model") or "").strip()
	if not model:
		return None
	if provider == "Ollama":
		base = (settings.get("ollama_base_url") or "").rstrip("/")
		if not base:
			return None
		return f"{base}/api/embeddings", {}, "ollama", model
	if provider == "OpenAI":
		key = _password(settings, "openai_api_key") or _password(settings, "embedding_api_key")
		if not key:
			return None
		return (
			"https://api.openai.com/v1/embeddings",
			{"Authorization": f"Bearer {key}"},
			"openai",
			model,
		)
	base = (settings.get("embedding_base_url") or settings.get("compatible_base_url") or "").rstrip("/")
	if not base:
		return None
	if base.endswith("/embeddings"):
		url = base
	elif base.endswith("/v1"):
		url = base + "/embeddings"
	else:
		url = base + "/v1/embeddings"
	key = _password(settings, "embedding_api_key") or _password(settings, "compatible_api_key")
	headers = {"Authorization": f"Bearer {key}"} if key else {}
	return url, headers, "openai", model


def is_semantic_search_ready(settings=None) -> bool:
	settings = settings if settings is not None else get_settings()
	if not settings or not settings.get("enable_semantic_search") or not settings.get("qdrant_enabled"):
		return False
	if not settings.get("qdrant_url"):
		return False
	return _embedding_endpoint(settings) is not None


def embedding_available() -> bool:
	return is_semantic_search_ready(get_settings())


def embed_text(text: str, task: str = "search_document") -> list[float] | None:
	settings = get_settings()
	if not settings.get("enable_semantic_search") or not settings.get("qdrant_enabled"):
		return None
	text = (text or "").strip()
	if not text:
		return None
	endpoint = _embedding_endpoint(settings)
	if not endpoint:
		return None
	url, headers, style, model = endpoint
	prompt = _apply_task_prefix(text, model, task)
	if style == "ollama":
		response = requests.post(
			url,
			json={"model": model, "prompt": prompt},
			headers=headers,
			timeout=_TIMEOUT_SECONDS,
		)
		response.raise_for_status()
		return response.json().get("embedding")
	response = requests.post(
		url,
		json={"model": model, "input": prompt},
		headers=headers,
		timeout=_TIMEOUT_SECONDS,
	)
	response.raise_for_status()
	data = response.json().get("data") or []
	return data[0]["embedding"] if data else None
