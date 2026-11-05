# Copyright (c) 2026, Shaid Azmin and contributors
# For license information, please see license.txt

"""Read MCP Settings without assuming the Single has been saved yet."""

from __future__ import annotations

import frappe

DEFAULTS = {
	"enable_ai_assistant": 0,
	"enable_query_logging": 1,
	"enable_tool_logging": 1,
	"enable_reports_tool": 1,
	"max_result_rows": 500,
	"query_timeout_seconds": 30,
	"schema_cache_ttl_minutes": 60,
	"log_retention_days": 90,
	"allow_read": 1,
	"allow_create": 1,
	"allow_update": 1,
	"allow_cancel": 0,
	"allow_delete": 0,
	"allow_submit": 0,
	"llm_provider": "Ollama",
	"ollama_base_url": "http://localhost:11434",
	"ollama_model": "llama3.1:8b",
	"openai_model": "gpt-4o-mini",
	"embedding_provider": "Follow LLM",
	"qdrant_url": "http://localhost:6333",
	"enable_semantic_search": 0,
	"qdrant_enabled": 0,
	"default_rate_limit": 120,
	"mcp_allowed_origins": "*",
}


def get_settings():
	"""Cached MCP Settings document, or defaults when the Single has no row."""
	try:
		return frappe.get_cached_doc("MCP Settings")
	except Exception:
		return frappe._dict(DEFAULTS)


def setting(name, default=None):
	value = get_settings().get(name)
	if value in (None, ""):
		return DEFAULTS.get(name, default)
	return value


def as_bool(value) -> bool:
	if isinstance(value, bool):
		return value
	if isinstance(value, (int, float)):
		return bool(value)
	return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}
