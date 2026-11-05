# Copyright (c) 2026, Shaid Azmin and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class MCPSettings(Document):
	def validate(self):
		if not self.qdrant_collection_prefix:
			self.qdrant_collection_prefix = frappe.scrub(frappe.local.site or "default")
		self.validate_limits()
		self.validate_provider()
		self.capture_semantic_readiness()

	def on_update(self):
		self.maybe_index()

	def validate_limits(self):
		if int(self.max_result_rows or 0) < 1:
			frappe.throw(_("Maximum Result Rows must be at least 1."))
		if int(self.query_timeout_seconds or 0) < 1:
			frappe.throw(_("Query Timeout must be at least 1 second."))
		if int(self.schema_cache_ttl_minutes or 0) < 1:
			frappe.throw(_("Schema Cache TTL must be at least 1 minute."))

	def validate_provider(self):
		if self.enable_ai_assistant:
			if self.llm_provider == "Ollama" and not self.ollama_base_url:
				frappe.throw(_("Ollama Base URL is required when the assistant is enabled."))
			if self.llm_provider == "OpenAI" and not self.get_password("openai_api_key", raise_exception=False):
				frappe.throw(_("OpenAI API Key is required when the assistant is enabled."))
			if self.llm_provider == "Compatible" and not self.compatible_base_url:
				frappe.throw(_("Base URL is required when the assistant is enabled."))
			if self.llm_provider == "Compatible" and not self.compatible_model:
				frappe.throw(_("Model is required when the provider is Compatible."))
		if self.qdrant_enabled and not self.qdrant_url:
			frappe.throw(_("Qdrant URL is required when Qdrant is enabled."))
		if self.enable_semantic_search and self.qdrant_enabled and not (self.embedding_model or "").strip():
			frappe.throw(_("Embedding Model is required when semantic search and Qdrant are enabled."))

	def capture_semantic_readiness(self):
		from frappe_mcp.ai.embeddings import is_semantic_search_ready

		previous = frappe.db.get_singles_dict(self.doctype, cast=True)
		self.flags.was_semantic_search_ready = is_semantic_search_ready(previous)

	def maybe_index(self):
		from frappe_mcp.ai.embeddings import is_semantic_search_ready

		was_ready = bool(self.flags.get("was_semantic_search_ready"))
		now_ready = is_semantic_search_ready(self)
		if now_ready and not was_ready:
			frappe.enqueue(
				"frappe_mcp.ai.semantic.run_initial_index",
				queue="long",
				enqueue_after_commit=True,
			)
			frappe.msgprint(
				_(
					"Semantic search is configured. Indexing runs in the background once. Later saves stay in sync on their own."
				),
				alert=True,
				indicator="blue",
			)
