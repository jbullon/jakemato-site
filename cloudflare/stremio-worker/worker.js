const ORIGIN = "https://raw.githubusercontent.com/jbullon/jakemato-site/master/stremio/movies";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
  "Access-Control-Allow-Headers": "*",
};

function withCors(headers) {
  const merged = new Headers(headers);
  for (const [key, value] of Object.entries(corsHeaders)) {
    merged.set(key, value);
  }
  return merged;
}

function isAllowedPath(pathname) {
  if (pathname === "/manifest.json") return true;
  if (pathname.startsWith("/catalog/movie/") && pathname.endsWith(".json")) return true;
  return false;
}

export default {
  async fetch(request) {
    const url = new URL(request.url);

    if (request.method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: corsHeaders,
      });
    }

    if (!["GET", "HEAD"].includes(request.method)) {
      return new Response("Method not allowed", {
        status: 405,
        headers: withCors({ "Content-Type": "text/plain; charset=utf-8" }),
      });
    }

    if (!isAllowedPath(url.pathname)) {
      return new Response("Not found", {
        status: 404,
        headers: withCors({ "Content-Type": "text/plain; charset=utf-8" }),
      });
    }

    const upstreamUrl = ORIGIN + url.pathname + url.search;

    try {
      const upstream = await fetch(upstreamUrl, {
        cf: {
          cacheTtl: 300,
          cacheEverything: true,
        },
      });

      const headers = withCors(upstream.headers);
      headers.set("Cache-Control", "public, max-age=300");

      return new Response(request.method === "HEAD" ? null : upstream.body, {
        status: upstream.status,
        statusText: upstream.statusText,
        headers,
      });
    } catch (error) {
      return new Response(
        JSON.stringify({
          error: "Failed to fetch Jakemato Stremio data",
        }),
        {
          status: 502,
          headers: withCors({
            "Content-Type": "application/json; charset=utf-8",
          }),
        }
      );
    }
  },
};
