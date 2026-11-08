# Shopwright widget

Embeddable storefront chat widget: vanilla TypeScript, no runtime dependencies, about 6 KB built.
It renders inside a shadow root, so the store's CSS cannot change it and it cannot change the store.

## Build

```bash
npm ci
npm run build   # writes dist/widget.js
```

## Embed

Host `dist/widget.js` anywhere (a CDN or the API's static files) and add one tag to the theme:

```html
<script src="https://cdn.example.com/widget.js"
        data-api="https://api.example.com"
        data-shop="your-store.myshopify.com" defer></script>
```

## How it authenticates

1. `POST /v1/widget/session` with the shop domain returns a widget token valid for one hour.
2. Every `POST /v1/chat` carries it as a bearer token. The API reads the store from the token,
   never from the request body, so a shopper cannot point the widget at another store's data.
3. The widget refreshes the token a minute before it expires and retries once on a 401.

Replies are rendered with `textContent` only, because they can quote store content, which is
untrusted. Citation links are shown only for `http` and `https` URLs.
