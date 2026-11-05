# Copyright (c) 2026, Shaid Azmin and contributors
# For license information, please see license.txt

import hashlib
import json
import secrets

import frappe
from frappe import _
from frappe.model.document import Document


def generate_token():
	raw = "fmcp_" + secrets.token_urlsafe(32)
	digest = hashlib.sha256(raw.encode()).hexdigest()
	return raw, digest, raw[:12]


class MCPConnector(Document):
	def before_validate(self):
		if not self.naming_series:
			self.naming_series = "MCP-.YYYY.-.#####"

	def before_insert(self):
		if not self.naming_series:
			self.naming_series = "MCP-.YYYY.-.#####"

	def validate(self):
		self.check_user()
		self.check_one_connector()
		self.set_user_labels()
		if not self.token_hash:
			if self.is_new():
				self.issue_token()
			else:
				self.token_hash = frappe.db.get_value(self.doctype, self.name, "token_hash")
				self.token_prefix = self.token_prefix or frappe.db.get_value(
					self.doctype, self.name, "token_prefix"
				)
		if self.rate_limit_per_minute in (None, ""):
			self.rate_limit_per_minute = 120
		self.endpoint = endpoint_url()
		self.client_config = config_template(self.connector_name)

	def check_user(self):
		if not self.user:
			self.user = frappe.session.user
		if not frappe.db.get_value("User", self.user, "enabled"):
			frappe.throw(_("User {0} is disabled.").format(self.user))
		if frappe.session.user != "Administrator" and "System Manager" not in frappe.get_roles():
			if self.user != frappe.session.user:
				frappe.throw(_("You can only create a connector for your own user."))

	def check_one_connector(self):
		if not self.is_new() and not self.has_value_changed("user"):
			return
		existing = frappe.db.get_value(
			"MCP Connector",
			{"user": self.user, "name": ["!=", self.name or ""]},
			"name",
		)
		if existing:
			frappe.throw(
				_("User {0} already has connector {1}. One user can have only one MCP connector.").format(
					self.user, existing
				)
			)

	def set_user_labels(self):
		full_name, email = frappe.db.get_value("User", self.user, ["full_name", "email"]) or (
			None,
			None,
		)
		self.user_full_name = full_name or self.user
		self.user_email = email or self.user

	def issue_token(self):
		raw, digest, prefix = generate_token()
		self.token_hash = digest
		self.token_prefix = prefix
		self.api_token = raw
		self.flags.plain_token = raw
		return raw

	def on_update(self):
		token = self.flags.get("plain_token")
		if not token or self.flags.get("skip_token_dialog"):
			return
		frappe.msgprint(
			token_dialog_html(self.connector_name, token),
			title=_("MCP token"),
			indicator="green",
			wide=True,
		)

	def config_with_token(self, token):
		return config_with_token(self.connector_name, token)


def endpoint_url():
	return frappe.utils.get_url("/mcp")


def server_url(token):
	"""Same shape as Zoho: https://host/mcp/<key>/message"""
	return endpoint_url().rstrip("/") + "/" + token + "/message"


def config_template(connector_name):
	return config_with_token(connector_name, "<token>")


def token_dialog_html(connector_name, token):
	"""HTML, not plain newlines. The desk message dialog collapses whitespace,
	which jammed the token and the JSON config onto one line."""
	safe_token = frappe.utils.escape_html(token)
	safe_url = frappe.utils.escape_html(server_url(token))
	config = frappe.utils.escape_html(config_with_token(connector_name, token))
	return (
		"<p>Paste the server URL into the MCP client. The key is inside the link.</p>"
		"<p><b>Server URL</b></p>"
		f"<pre style='white-space:pre-wrap;word-break:break-all;user-select:all'>{safe_url}</pre>"
		"<p><b>Token</b></p>"
		f"<pre style='white-space:pre-wrap;word-break:break-all;user-select:all'>{safe_token}</pre>"
		"<p><b>Client config</b></p>"
		f"<pre style='white-space:pre-wrap;word-break:break-all;user-select:all'>{config}</pre>"
	)


def config_with_token(connector_name, token):
	slug = frappe.scrub(connector_name or "frappe") or "frappe"
	return json.dumps(
		{
			"mcpServers": {
				slug: {
					"url": endpoint_url(),
					"headers": {
						"Authorization": f"Bearer {token}",
						"x-api-key": token,
					},
				}
			}
		},
		indent=2,
	)
