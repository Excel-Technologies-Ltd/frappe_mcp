app_name = "frappe_mcp"
app_title = "Frappe MCP"
app_publisher = "Shaid Azmin"
app_description = "Universal MCP server for any Frappe app"
app_email = "query@avolytic.com"
app_license = "MIT"

app_include_js = "frappe_mcp.bundle.js"
app_include_css = "/assets/frappe_mcp/css/mcp_chat.css"

after_install = "frappe_mcp.install.after_install"
before_migrate = "frappe_mcp.install.before_migrate"
after_migrate = "frappe_mcp.install.after_migrate"

auth_hooks = ["frappe_mcp.mcp.auth.authenticate_request"]

page_renderer = [
	"frappe_mcp.mcp.oauth_page.OAuthPage",
	"frappe_mcp.mcp.renderer.MCPPage",
]

extend_bootinfo = ["frappe_mcp.boot.bootinfo"]

has_permission = {
	"MCP Connector": "frappe_mcp.permissions.connector_has_permission",
	"MCP Chat Session": "frappe_mcp.permissions.chat_has_permission",
}

permission_query_conditions = {
	"MCP Connector": "frappe_mcp.permissions.connector_query_conditions",
	"MCP Chat Session": "frappe_mcp.permissions.chat_query_conditions",
}

doc_events = {
	"DocType": {
		"on_update": "frappe_mcp.ai.hooks.clear_schema_cache_for_doctype",
		"on_trash": "frappe_mcp.ai.hooks.clear_schema_cache_for_doctype",
	},
	"Custom Field": {
		"on_update": "frappe_mcp.ai.hooks.clear_schema_cache_for_custom_field",
		"on_trash": "frappe_mcp.ai.hooks.clear_schema_cache_for_custom_field",
	},
	"*": {
		"on_update": "frappe_mcp.ai.hooks.index_record_for_semantic_search",
		"on_trash": "frappe_mcp.ai.hooks.remove_record_from_semantic_index",
	},
}

scheduler_events = {
	"daily": ["frappe_mcp.tasks.daily"],
}
