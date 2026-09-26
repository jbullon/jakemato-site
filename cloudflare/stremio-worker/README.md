# Jakemato Stremio CORS Worker

This Cloudflare Worker fronts the static Stremio addon files hosted on Jakemato/GitHub Pages and adds the CORS headers Stremio needs.

## Public routes

The Worker intentionally exposes only:

- `/manifest.json`
- `/catalog/movie/*.json`

Each allowed request is proxied to:

`https://jakemato.com/stremio/movies<request-path>`

Example:

`https://<worker>.workers.dev/manifest.json`

proxies to:

`https://jakemato.com/stremio/movies/manifest.json`

## Cloudflare dashboard deployment

1. Cloudflare dashboard → **Workers & Pages**.
2. Select **Create application** → **Create Worker**.
3. Name it `jakemato-stremio`.
4. Deploy the starter Worker.
5. Open the Worker editor, replace the starter code with `worker.js`, then deploy again.
6. Open the resulting `workers.dev` URL with `/manifest.json`.
7. Use that HTTPS manifest URL in Stremio.

No secrets or environment variables are required.
