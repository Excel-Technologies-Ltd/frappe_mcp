frappe.pages["mcp-connect"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Connect"),
		single_column: true,
	});

	page.main.html(`
		<style>
			.mcp-connect { max-width: 760px; margin: 28px auto 40px; }
			.mcp-connect h1 { font-size: 22px; margin: 0 0 6px; text-align: center; }
			.mcp-connect .mcp-sub { color: var(--text-muted); text-align: center; margin: 0 0 22px; }
			.mcp-connect .mcp-card {
				background: var(--card-bg);
				border: 1px solid var(--border-color);
				border-radius: 12px;
				padding: 18px 18px 16px;
			}
			.mcp-connect .mcp-label-row { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
			.mcp-connect .mcp-label { font-weight: 650; }
			.mcp-connect .mcp-hint { color: var(--text-muted); font-size: 12px; margin-top: 2px; }
			.mcp-connect .mcp-regen { background: none; border: 0; color: var(--text-color); cursor: pointer; padding: 0; }
			.mcp-connect .mcp-url-row { display: flex; gap: 8px; margin-top: 14px; }
			.mcp-connect .mcp-url {
				flex: 1;
				border: 1px solid var(--border-color);
				border-radius: 8px;
				padding: 10px 12px;
				background: var(--control-bg);
				font-family: var(--font-stack);
			}
			.mcp-connect .mcp-copy {
				border: 1px solid var(--border-color);
				background: var(--card-bg);
				border-radius: 8px;
				padding: 0 12px;
				cursor: pointer;
			}
		</style>
		<div class="mcp-connect">
			<h1>${__("Connect to Your Frappe MCP Server")}</h1>
			<p class="mcp-sub">${__("Paste this server URL into your MCP client. Open this page on your public https address before you copy.")}</p>
			<div class="mcp-card">
				<div class="mcp-label-row">
					<div>
						<div class="mcp-label">${__("Server URL")}</div>
						<div class="mcp-hint">${__("The URL to connect this Frappe MCP server")}</div>
					</div>
					<button type="button" class="mcp-regen">${__("Regenerate API Key")}</button>
				</div>
				<div class="mcp-url-row">
					<input class="mcp-url" readonly value="">
					<button type="button" class="mcp-copy" title="${__("Copy")}">${__("Copy")}</button>
				</div>
			</div>
		</div>
	`);

	const $url = page.main.find(".mcp-url");
	const $copy = page.main.find(".mcp-copy");
	let full = "";

	function paint(data) {
		data = data || {};
		const path = data.path || "";
		full = path ? window.location.origin + path : "";
		const shown = full
			? full.replace(/\/mcp\/[^/]+\/message$/, "/mcp/**********/message")
			: __("Regenerate API Key to create your server URL");
		$url.val(shown);
		$copy.prop("disabled", !full);
	}

	function load() {
		frappe.call({
			method: "frappe_mcp.api.connect.mine",
			callback(response) {
				paint(response.message || {});
			},
		});
	}

	page.main.on("click", ".mcp-copy", () => {
		if (!full) {
			return;
		}
		frappe.utils.copy_to_clipboard(full);
		frappe.show_alert({ message: __("Server URL copied"), indicator: "green" });
	});

	page.main.on("click", ".mcp-regen", () => {
		frappe.confirm(__("The current server URL stops working immediately. Continue?"), () => {
			frappe.call({
				method: "frappe_mcp.api.connect.regenerate",
				freeze: true,
				callback(response) {
					paint(response.message || {});
					frappe.show_alert({ message: __("API key regenerated"), indicator: "green" });
				},
			});
		});
	});

	load();
};
