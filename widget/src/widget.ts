// Shopwright storefront widget. Load with:
// <script src="https://api.example.com/widget.js" data-api="https://api.example.com"
//         data-shop="your-store.myshopify.com" defer></script>
// No framework and no dependencies; it renders inside a shadow root so store CSS cannot leak in.

interface Citation {
  label: string;
  title?: string;
  url?: string;
}

interface ChatReply {
  conversation_id: string;
  reply: string;
  citations: Citation[];
  handoff: boolean;
}

const STYLE = `
  :host { all: initial; font: 14px/1.4 system-ui, sans-serif; color: #1a1a1a; }
  button { font: inherit; cursor: pointer; }
  .launcher { position: fixed; right: 20px; bottom: 20px; border: 0; border-radius: 24px;
    padding: 12px 18px; background: #1a1a1a; color: #fff; z-index: 2147483000; }
  .panel { position: fixed; right: 20px; bottom: 76px; width: min(360px, calc(100vw - 40px));
    height: min(520px, calc(100vh - 120px)); display: flex; flex-direction: column;
    background: #fff; border: 1px solid #ddd; border-radius: 12px; z-index: 2147483000;
    box-shadow: 0 8px 30px rgba(0, 0, 0, 0.15); }
  .panel[hidden] { display: none; }
  .log { flex: 1; overflow-y: auto; padding: 12px; display: flex; flex-direction: column; gap: 8px; }
  .msg { max-width: 85%; padding: 8px 12px; border-radius: 10px; white-space: pre-wrap; }
  .user { align-self: flex-end; background: #1a1a1a; color: #fff; }
  .bot { align-self: flex-start; background: #f2f2f2; }
  .note { align-self: center; color: #666; font-size: 12px; }
  .sources { margin-top: 6px; font-size: 12px; }
  .sources a { color: inherit; }
  form { display: flex; gap: 8px; padding: 10px; border-top: 1px solid #eee; }
  input { flex: 1; font: inherit; padding: 8px 10px; border: 1px solid #ccc; border-radius: 8px; }
  form button { border: 0; border-radius: 8px; padding: 8px 12px; background: #1a1a1a; color: #fff; }
  form button:disabled { opacity: 0.5; }
`;

class ShopwrightWidget {
  private token = "";
  private tokenExpiresAt = 0;
  private conversationId: string | null = null;
  private readonly log: HTMLElement;
  private readonly input: HTMLInputElement;
  private readonly send: HTMLButtonElement;

  constructor(
    private readonly api: string,
    private readonly shop: string,
    root: ShadowRoot,
  ) {
    const style = document.createElement("style");
    style.textContent = STYLE;
    const launcher = el("button", "launcher", "Ask us");
    const panel = el("div", "panel");
    panel.hidden = true;
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-label", "Store assistant");
    this.log = el("div", "log");
    this.log.setAttribute("aria-live", "polite");
    const form = el("form");
    this.input = el("input") as HTMLInputElement;
    this.input.placeholder = "Ask about products, shipping, or an order";
    this.input.maxLength = 2000;
    this.send = el("button", "", "Send") as HTMLButtonElement;
    form.append(this.input, this.send);
    panel.append(this.log, form);
    root.append(style, panel, launcher);

    launcher.addEventListener("click", () => {
      panel.hidden = !panel.hidden;
      if (!panel.hidden) this.input.focus();
    });
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      void this.ask(this.input.value.trim());
    });
  }

  private async ask(message: string): Promise<void> {
    if (!message) return;
    this.input.value = "";
    this.append("user", message);
    this.send.disabled = true;
    try {
      const reply = await this.post<ChatReply>("/v1/chat", {
        message,
        conversation_id: this.conversationId,
      });
      this.conversationId = reply.conversation_id;
      this.append("bot", reply.reply, reply.citations);
      if (reply.handoff) this.append("note", "A person from the store will follow up.");
    } catch {
      this.append("note", "Sorry, something went wrong. Please try again.");
    } finally {
      this.send.disabled = false;
      this.input.focus();
    }
  }

  private async post<T>(path: string, body: unknown): Promise<T> {
    let response = await this.request(path, body);
    if (response.status === 401) {
      this.tokenExpiresAt = 0; // token expired early or the secret rotated; retry once
      response = await this.request(path, body);
    }
    if (!response.ok) throw new Error(`${path} returned ${response.status}`);
    return (await response.json()) as T;
  }

  private async request(path: string, body: unknown): Promise<Response> {
    const token = await this.session();
    return fetch(this.api + path, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify(body),
    });
  }

  private async session(): Promise<string> {
    // Refresh a minute early so a token never expires mid-request.
    if (this.token && Date.now() < this.tokenExpiresAt - 60_000) return this.token;
    const response = await fetch(this.api + "/v1/widget/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ shop: this.shop }),
    });
    if (!response.ok) throw new Error(`session returned ${response.status}`);
    const data = (await response.json()) as { token: string; expires_in: number };
    this.token = data.token;
    this.tokenExpiresAt = Date.now() + data.expires_in * 1000;
    return this.token;
  }

  private append(kind: "user" | "bot" | "note", text: string, citations: Citation[] = []): void {
    // textContent only: replies can quote store content, which is untrusted.
    const bubble = el("div", `msg ${kind}`, text);
    const links = citations.filter((c) => c.url && /^https?:\/\//.test(c.url));
    if (links.length > 0) {
      const sources = el("div", "sources", "Sources: ");
      links.forEach((c, i) => {
        const a = el("a", "", c.title || c.label) as HTMLAnchorElement;
        a.href = c.url as string;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        sources.append(...(i > 0 ? [", ", a] : [a]));
      });
      bubble.append(sources);
    }
    this.log.append(bubble);
    this.log.scrollTop = this.log.scrollHeight;
  }
}

function el(tag: string, className = "", text = ""): HTMLElement {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
}

(() => {
  const script = document.currentScript as HTMLScriptElement | null;
  const api = script?.dataset.api?.replace(/\/$/, "");
  const shop = script?.dataset.shop;
  if (!api || !shop) {
    console.warn("shopwright: data-api and data-shop are required on the script tag");
    return;
  }
  const host = document.createElement("div");
  document.body.append(host);
  new ShopwrightWidget(api, shop, host.attachShadow({ mode: "open" }));
})();
