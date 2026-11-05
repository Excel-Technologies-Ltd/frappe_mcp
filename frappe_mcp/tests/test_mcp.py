# Copyright (c) 2026, Shaid Azmin and contributors
# For license information, please see license.txt

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_mcp.mcp.auth import authenticate_request, bearer_token, find_connector, ip_allowed, token_hash
from frappe_mcp.mcp.protocol import handle_message
from frappe_mcp.policy import bind_policy
from frappe_mcp.tools.guards import redact_record, resolve_date_phrase
from frappe_mcp.tools.registry import call_tool, tool_names


def _user(email):
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"send_welcome_email": 0,
				"enabled": 1,
			}
		).insert(ignore_permissions=True)
	return email


def _policy(**overrides):
	policy = {
		"allow_read": True,
		"allow_create": True,
		"allow_update": True,
		"allow_cancel": False,
		"allow_delete": False,
		"allow_submit": False,
		"reports": False,
		"semantic": False,
		"allowed_doctypes": [],
		"blocked_doctypes": [],
		"connector": None,
		"source": "test",
	}
	policy.update(overrides)
	return policy


class TestMCPCore(FrappeTestCase):
	def setUp(self):
		bind_policy(_policy())
		frappe.set_user("Administrator")

	def test_date_phrase_today(self):
		start, end = resolve_date_phrase("today")
		self.assertEqual(start, end)
		self.assertEqual(str(start), frappe.utils.today())

	def test_unknown_date_phrase_is_an_error(self):
		result = call_tool("resolve_date_range", {"phrase": "blue moon"})
		self.assertIn("error", result)

	def test_bad_filter_operator_never_reaches_sql(self):
		result = call_tool(
			"count_records",
			{"doctype": "ToDo", "filters_json": '{"status": ["drop table", 1]}'},
		)
		self.assertIn("error", result)

	def test_password_values_are_masked(self):
		schema = {"fields": [{"fieldname": "api_key", "fieldtype": "Data"}]}
		clean = redact_record({"name": "A", "api_key": "secret-value"}, schema)
		self.assertEqual(clean["api_key"], "***")
		self.assertEqual(clean["name"], "A")

	def test_cancel_and_delete_are_hidden_by_default(self):
		names = tool_names()
		self.assertIn("create_record", names)
		self.assertIn("update_record", names)
		self.assertIn("query_records", names)
		self.assertNotIn("cancel_document", names)
		self.assertNotIn("delete_document", names)
		self.assertNotIn("submit_document", names)
		blocked = call_tool(
			"delete_document",
			{"doctype": "ToDo", "name": "MISSING", "confirm": True},
		)
		self.assertIn("error", blocked)

	def test_create_preview_then_confirm(self):
		preview = call_tool(
			"create_record",
			{
				"doctype": "ToDo",
				"values_json": '{"description": "MCP test todo"}',
				"confirm": False,
			},
		)
		self.assertFalse(preview.get("created"))
		self.assertEqual(preview.get("action"), "create")
		created = call_tool(
			"create_record",
			{
				"doctype": "ToDo",
				"values_json": '{"description": "MCP test todo"}',
				"confirm": True,
			},
		)
		self.assertTrue(created.get("created"))
		self.assertTrue(frappe.db.exists("ToDo", created["name"]))

	def test_initialize_and_tool_list(self):
		response = handle_message(
			{
				"jsonrpc": "2.0",
				"id": 1,
				"method": "initialize",
				"params": {
					"protocolVersion": "2025-03-26",
					"capabilities": {},
					"clientInfo": {"name": "test", "version": "0"},
				},
			}
		)
		self.assertEqual(response["result"]["protocolVersion"], "2025-03-26")
		self.assertEqual(response["result"]["serverInfo"]["name"], "frappe-mcp")
		listed = handle_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
		names = [tool["name"] for tool in listed["result"]["tools"]]
		self.assertIn("get_record", names)
		self.assertNotIn("delete_document", names)

	def test_connector_token_authenticates_by_hash_only(self):
		doc = frappe.get_doc(
			{
				"doctype": "MCP Connector",
				"connector_name": "Test Connector",
				"user": _user("mcp-token@example.com"),
			}
		).insert()
		token = doc.flags.plain_token
		self.assertTrue(token.startswith("fmcp_"))
		self.assertTrue(doc.name.startswith("MCP-"))
		self.assertEqual(doc.token_hash, token_hash(token))
		self.assertNotIn(token, frappe.as_json(doc.as_dict()))
		found = find_connector(token)
		self.assertEqual(found.name, doc.name)
		self.assertIsNone(find_connector(token + "x"))

	def test_renderer_speaks_raw_jsonrpc(self):
		from frappe_mcp.mcp.renderer import MCPPage
		from frappe_mcp.policy import connector_policy

		doc = frappe.get_doc(
			{
				"doctype": "MCP Connector",
				"connector_name": "HTTP Connector",
				"user": _user("mcp-http@example.com"),
			}
		).insert()
		frappe.flags.mcp_connector = doc.name
		frappe.flags.mcp_policy = connector_policy(doc)
		frappe.flags.mcp_source = "MCP"
		body = json.dumps({"jsonrpc": "2.0", "id": 7, "method": "ping", "params": {}})
		frappe.request = frappe._dict(
			method="POST",
			path="/mcp",
			headers={"Origin": "https://example.com"},
			get_data=lambda as_text=False: body,
		)
		response = MCPPage("mcp").render()
		self.assertEqual(response.status_code, 200)
		payload = json.loads(response.get_data(as_text=True))
		self.assertEqual(payload["id"], 7)
		self.assertEqual(payload["result"], {})
		self.assertNotIn("message", payload)

		frappe.flags.mcp_connector = None
		frappe.set_user("Guest")
		denied = MCPPage("mcp").render()
		self.assertEqual(denied.status_code, 401)

	def test_one_connector_per_user(self):
		user = _user("mcp-one@example.com")
		first = frappe.get_doc(
			{
				"doctype": "MCP Connector",
				"connector_name": "Only One",
				"user": user,
			}
		).insert()
		self.assertEqual(first.user_email, user)
		self.assertTrue(first.user_full_name)
		second = frappe.get_doc(
			{
				"doctype": "MCP Connector",
				"connector_name": "Second",
				"user": user,
			}
		)
		self.assertRaises(frappe.ValidationError, second.insert)

	def test_bulk_create_all_users_in_role(self):
		from frappe_mcp.api.connector import bulk_create

		role = "MCP Bulk Test"
		if not frappe.db.exists("Role", role):
			frappe.get_doc(
				{"doctype": "Role", "role_name": role, "desk_access": 1}
			).insert(ignore_permissions=True)
		user = _user("mcp-role@example.com")
		other = _user("mcp-norole@example.com")
		frappe.get_doc("User", user).add_roles(role)
		result = bulk_create(all_users=1, role=role, connector_name="Role Batch")
		self.assertEqual([row["user"] for row in result["created"]], [user])
		self.assertEqual(result["created"][0]["connector_name"], "Role Batch")
		self.assertNotIn(other, [row["user"] for row in result["created"]])
		self.assertEqual(result["skipped"], 0)
		self.assertRaises(
			frappe.ValidationError,
			lambda: bulk_create(all_users=1, role=role, connector_name="Role Batch"),
		)

	def test_regenerate_opens_one_dialog(self):
		from frappe_mcp.api.connector import regenerate_token

		doc = frappe.get_doc(
			{
				"doctype": "MCP Connector",
				"connector_name": "Regen Once",
				"user": _user("mcp-regen@example.com"),
			}
		).insert()
		frappe.message_log[:] = []
		result = regenerate_token(doc.name)
		self.assertTrue(result["server_url"].endswith("/" + result["token"] + "/message"))
		self.assertEqual(frappe.message_log, [])

	def test_token_dialog_keeps_token_and_config_apart(self):
		from frappe_mcp.frappe_mcp.doctype.mcp_connector.mcp_connector import token_dialog_html

		html = token_dialog_html("ArcOne", "fmcp_example")
		self.assertIn("<pre", html)
		self.assertIn("fmcp_example", html)
		self.assertIn("mcpServers", html)
		self.assertLess(html.index("fmcp_example"), html.index("mcpServers"))

	def test_bulk_create_and_export_are_manager_only(self):
		from frappe_mcp.api.connector import bulk_create, export_connectors

		rows = bulk_create(
			users=[_user("mcp-bulk@example.com")], connector_name="Bulk One"
		)["created"]
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["connector_name"], "Bulk One")
		self.assertTrue(rows[0]["name"].startswith("MCP-"))
		self.assertTrue(rows[0]["token"].startswith("fmcp_"))
		self.assertIn("mcpServers", rows[0]["client_config"])
		export_connectors(names=[rows[0]["name"]])
		self.assertEqual(frappe.response["type"], "csv")
		self.assertIn("token_prefix", frappe.response["result"])
		self.assertNotIn(rows[0]["token"], frappe.response["result"])

		frappe.set_user("Guest")
		try:
			self.assertRaises(frappe.PermissionError, lambda: bulk_create(["Administrator"]))
		finally:
			frappe.set_user("Administrator")

	def test_server_url_uses_the_key_in_the_path(self):
		from frappe_mcp.api.connect import mine
		from frappe_mcp.frappe_mcp.doctype.mcp_connector.mcp_connector import server_url

		user = _user("mcp-url@example.com")
		if "MCP User" not in frappe.get_roles(user):
			frappe.get_doc("User", user).add_roles("MCP User")
		frappe.set_user(user)
		payload = mine()
		self.assertTrue(payload["server_url"].endswith("/message"))
		token = payload["server_url"].rstrip("/").split("/")[-2]
		self.assertTrue(token.startswith("fmcp_"))
		self.assertEqual(payload["server_url"], server_url(token))

		frappe.request = frappe._dict(method="POST", path=f"/mcp/{token}/message", headers={})
		frappe.set_user("Guest")
		authenticate_request()
		self.assertEqual(frappe.session.user, user)
		self.assertEqual(find_connector(bearer_token()).user, user)

		frappe.request.path = f"/mcp/{token}"
		self.assertEqual(bearer_token(), token)
		frappe.set_user("Administrator")

	def test_oauth_redirect_keeps_a_long_state(self):
		from frappe_mcp.mcp.oauth import authorize, ensure_default_client

		client = ensure_default_client()
		state = "g" * 900
		frappe.set_user("Administrator")
		frappe.request = frappe._dict(method="GET", full_path="/oauth/authorize", args={}, headers={})
		body, status = authorize(
			{
				"client_id": client.client_id,
				"redirect_uri": "https://oauth-redirect.googleusercontent.com/r/example",
				"response_type": "code",
				"code_challenge": "a" * 43,
				"code_challenge_method": "S256",
				"state": state,
			}
		)
		self.assertEqual(status, 200)
		self.assertIn(state, body)

		denied = authorize(
			{
				"client_id": client.client_id,
				"redirect_uri": "https://oauth-redirect.googleusercontent.com/r/example",
				"response_type": "code",
				"code_challenge": "a" * 43,
				"code_challenge_method": "plain",
				"state": state,
			}
		)
		location = denied.headers["Location"]
		self.assertIn("error=invalid_request", location)
		self.assertIn("state=" + state, location)

	def test_ip_allowlist(self):
		self.assertTrue(ip_allowed("", "10.0.0.8"))
		self.assertTrue(ip_allowed("10.0.0.0/24", "10.0.0.8"))
		self.assertFalse(ip_allowed("10.0.0.0/24", "10.1.0.8"))
		self.assertTrue(ip_allowed("10.0.0.8", "10.0.0.8"))
