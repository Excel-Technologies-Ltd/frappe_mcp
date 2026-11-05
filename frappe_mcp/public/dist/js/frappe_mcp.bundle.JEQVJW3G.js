(() => {
  // ../frappe_mcp/frappe_mcp/public/js/mcp_chat.js
  frappe.provide("frappe_mcp");
  frappe_mcp.chat = {
    init() {
      const boot = frappe.boot && frappe.boot.frappe_mcp || {};
      if (!boot.assistant_enabled || this.ready) {
        return;
      }
      this.ready = true;
      this.session = null;
      this.build();
    },
    build() {
      this.button = $(`
			<button class="mcp-assistant-launcher" type="button">MCP</button>
		`);
      this.panel = $(`
			<section class="mcp-assistant" hidden>
				<header class="mcp-assistant-header">
					<strong>Frappe MCP</strong>
					<span>
						<button type="button" class="btn btn-xs btn-default mcp-new">${__("New")}</button>
						<button type="button" class="btn btn-xs btn-default mcp-close">${__("Close")}</button>
					</span>
				</header>
				<div class="mcp-assistant-log"></div>
				<form class="mcp-assistant-form">
					<textarea rows="2" placeholder="${__("Ask about records you can access")}"></textarea>
					<button type="submit" class="btn btn-primary btn-sm">${__("Send")}</button>
				</form>
			</section>
		`);
      $("body").append(this.button).append(this.panel);
      this.log = this.panel.find(".mcp-assistant-log");
      this.input = this.panel.find("textarea");
      this.button.on("click", () => this.toggle());
      this.panel.find(".mcp-close").on("click", () => this.panel.attr("hidden", true));
      this.panel.find(".mcp-new").on("click", () => this.reset());
      this.panel.find("form").on("submit", (event) => {
        event.preventDefault();
        this.send();
      });
    },
    toggle() {
      const hidden = this.panel.attr("hidden");
      if (hidden) {
        this.panel.removeAttr("hidden");
        this.input.focus();
      } else {
        this.panel.attr("hidden", true);
      }
    },
    reset() {
      this.session = null;
      this.log.empty();
    },
    add(role, text) {
      const line = $('<div class="mcp-line"></div>');
      line.addClass(role === "User" ? "mcp-user" : "mcp-bot");
      line.text(text || "");
      this.log.append(line);
      this.log.scrollTop(this.log.prop("scrollHeight"));
    },
    send() {
      const query = (this.input.val() || "").trim();
      if (!query) {
        return;
      }
      this.input.val("");
      this.add("User", query);
      this.add("Assistant", __("Working..."));
      const pending = this.log.children().last();
      frappe.call({
        method: "frappe_mcp.api.assistant.ask",
        args: { query, session_name: this.session },
        callback: (response) => {
          const data = response.message || {};
          this.session = data.session || this.session;
          pending.text(data.answer || __("No answer."));
        },
        error: () => {
          pending.text(__("The assistant could not answer. Check MCP Settings and the error log."));
        }
      });
    }
  };
  $(document).on("app_ready", () => {
    frappe_mcp.chat.init();
  });
})();
//# sourceMappingURL=frappe_mcp.bundle.JEQVJW3G.js.map
