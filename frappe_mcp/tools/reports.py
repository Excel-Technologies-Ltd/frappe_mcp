# Copyright (c) 2026, Shaid Azmin and contributors
# For license information, please see license.txt

"""Reports and semantic search. Both are optional and report that clearly
when MCP Settings has them off, so a model can fall back to query_records.
"""

from __future__ import annotations

import json

import frappe

from frappe_mcp.policy import assert_action, current_policy
from frappe_mcp.settings import get_settings
from frappe_mcp.tools.guards import assert_queryable, clamp_limit, max_result_rows, parse_json_object

_REPORT_CAP = 30


def _reports_enabled() -> bool:
	return bool(current_policy().get("reports")) and bool(get_settings().get("enable_reports_tool"))


def _report_permitted(row) -> bool:
	if not row.ref_doctype:
		return True
	return bool(frappe.has_permission(row.ref_doctype, "report"))


def _default_company() -> str | None:
	if not frappe.db.exists("DocType", "Company"):
		return None
	company = frappe.defaults.get_global_default("company")
	if company:
		return company
	companies = frappe.get_all("Company", limit_page_length=2, pluck="name")
	return companies[0] if len(companies) == 1 else None


def _current_fiscal_year() -> dict | None:
	if not frappe.db.exists("DocType", "Fiscal Year"):
		return None
	rows = frappe.get_all(
		"Fiscal Year",
		filters={
			"year_start_date": ["<=", frappe.utils.today()],
			"year_end_date": [">=", frappe.utils.today()],
		},
		fields=["name", "year_start_date", "year_end_date"],
		limit_page_length=1,
	)
	return rows[0] if rows else None


def _fill_report_defaults(filters: dict) -> dict:
	filled = dict(filters)
	if "company" not in filled:
		company = _default_company()
		if company:
			filled["company"] = company
	fiscal_year = None
	needed = (
		"fiscal_year",
		"from_fiscal_year",
		"to_fiscal_year",
		"from_date",
		"to_date",
		"period_start_date",
		"period_end_date",
	)
	if any(key not in filled for key in needed):
		fiscal_year = _current_fiscal_year()
	if fiscal_year:
		filled.setdefault("fiscal_year", fiscal_year.name)
		filled.setdefault("from_fiscal_year", fiscal_year.name)
		filled.setdefault("to_fiscal_year", fiscal_year.name)
		filled.setdefault("from_date", str(fiscal_year.year_start_date))
		filled.setdefault("to_date", str(fiscal_year.year_end_date))
		filled.setdefault("period_start_date", str(fiscal_year.year_start_date))
		filled.setdefault("period_end_date", str(fiscal_year.year_end_date))
	filled.setdefault("filter_based_on", "Fiscal Year")
	filled.setdefault("periodicity", "Yearly")
	return filled


def _report_columns(raw_columns) -> list[dict]:
	columns = []
	for column in raw_columns or []:
		if isinstance(column, dict):
			columns.append({"fieldname": column.get("fieldname"), "label": column.get("label")})
		else:
			parts = str(column).split(":")
			columns.append({"fieldname": parts[0], "label": parts[1] if len(parts) > 1 else parts[0]})
	return columns


def list_reports(search: str = "") -> dict:
	assert_action("read")
	if not _reports_enabled():
		return {"available": False, "message": "The reports tool is disabled in MCP Settings."}
	rows = frappe.get_list(
		"Report",
		filters={"disabled": 0},
		fields=["name", "report_type", "ref_doctype", "module"],
		order_by="name",
		limit_page_length=0,
	)
	if search:
		needle = search.lower()
		rows = [
			row
			for row in rows
			if needle in (row.name or "").lower()
			or needle in (row.ref_doctype or "").lower()
			or needle in (row.module or "").lower()
		]
	rows = [row for row in rows if _report_permitted(row)]
	preview = [
		{
			"report": row.name,
			"report_type": row.report_type,
			"ref_doctype": row.ref_doctype,
			"module": row.module,
		}
		for row in rows[:_REPORT_CAP]
	]
	out = {"available": True, "reports": preview}
	if len(rows) > _REPORT_CAP:
		out["note"] = f"Showing {_REPORT_CAP} of {len(rows)}. Narrow search."
	return out


def run_report(report_name: str, filters_json="{}") -> dict:
	assert_action("read")
	if not _reports_enabled():
		return {"available": False, "message": "The reports tool is disabled in MCP Settings."}
	report = frappe.db.get_value("Report", report_name, ["report_type", "ref_doctype", "disabled"], as_dict=True)
	if not report or report.disabled:
		frappe.throw(frappe._("'{0}' is not an available report. Use list_reports.").format(report_name))
	if report.report_type == "Report Builder":
		frappe.throw(
			frappe._(
				"'{0}' is a Report Builder saved list. Use query_records on {1} instead."
			).format(report_name, report.ref_doctype)
		)
	filters = parse_json_object(filters_json, "filters_json")
	filters = _fill_report_defaults(filters)
	from frappe.desk.query_report import run as run_query_report

	result = run_query_report(report_name, filters=filters)
	all_rows = result.get("result") or []
	limit = max_result_rows()
	truncated = len(all_rows) > limit
	out = {
		"available": True,
		"report": report_name,
		"filters_used": filters,
		"doctype": report.ref_doctype,
		"columns": _report_columns(result.get("columns")),
		"result": all_rows[:limit],
	}
	if result.get("report_summary"):
		out["summary"] = result["report_summary"]
	if truncated:
		out["note"] = f"Showing the first {limit} of {len(all_rows)} rows."
	return out


def semantic_search_records(query_text: str, doctype: str = "", limit: int = 5) -> dict:
	assert_action("read")
	from frappe_mcp.ai.embeddings import embedding_available
	from frappe_mcp.ai.semantic import semantic_search_records as search_records

	if not current_policy().get("semantic") or not embedding_available():
		return {
			"available": False,
			"message": "Semantic search is off. Enable Semantic Search, Qdrant, and an Embedding Model in MCP Settings.",
		}
	doctype = (doctype or "").strip()
	if doctype:
		assert_queryable(doctype)
	hits = search_records(query_text, doctype=doctype or None, limit=clamp_limit(limit, default=5))
	return {
		"available": True,
		"query": query_text,
		"doctype": doctype or None,
		"matches": hits,
		"note": "Matches are candidates. Call get_record before stating field values as fact.",
	}


def semantic_search_doctypes(query_text: str, limit: int = 5) -> dict:
	assert_action("read")
	from frappe_mcp.ai.embeddings import embedding_available
	from frappe_mcp.ai.semantic import semantic_search_doctypes as search_doctypes

	if not current_policy().get("semantic") or not embedding_available():
		return {"available": False, "message": "Semantic search is off in MCP Settings."}
	hits = search_doctypes(query_text, limit=clamp_limit(limit, default=5))
	return {"available": True, "query": query_text, "matches": hits}


def dumps(payload) -> str:
	return json.dumps(payload, default=str)
