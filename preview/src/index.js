// LeadScout preview host: one Cloudflare Worker that serves the static demo pages and three small routes.
// It stores no lead data: a view is a slug and a time, an unsubscribe is a token and a time. No IPs, no cookies.
//
//   GET  /v/<slug>     view ping from a 1x1 image on each demo page (at most one per demo per 30 minutes)
//   GET  /u/<token>    unsubscribe page with one confirm button
//   POST /u/<token>    the unsubscribe itself, also the RFC 8058 one-click POST from mail apps
//   GET  /api/sync     (bearer SYNC_SECRET) views and unsubscribes not yet handed to LeadScout
//   POST /api/ack      (bearer SYNC_SECRET) LeadScout saved these keys: delete them here
//   anything else      the static pages (env.ASSETS)
//
// Bindings (wrangler config, written by `leadscout demos publish`): ASSETS, EVENTS (Workers KV), STUDIO (text), SYNC_SECRET (secret).

const ID = /^[A-Za-z0-9_-]{16,64}$/; // slugs and tokens: secrets.token_urlsafe(16) is 22 characters
const SEEN_SECONDS = 1800;
const MAX_ITEMS = 1000;
// Per-route limits per minute, per Worker instance. Kept in memory only and never written anywhere.
const LIMITS = { view: 30, unsub: 10, api: 30, page: 120 };

const GIF = Uint8Array.from(atob("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"), (c) => c.charCodeAt(0));

export default {
  fetch: (request, env) => handle(request, env),
};

export async function handle(request, env, now = Date.now()) {
  const url = new URL(request.url);
  const path = url.pathname;
  let m;
  let res;
  const kind = path.startsWith("/v/") ? "view" : path.startsWith("/u/") ? "unsub" : path.startsWith("/api/") ? "api" : "page";
  if (!allow(kind, request, now)) {
    res = text("Too many requests. Try again in a minute.", 429);
  } else if ((m = path.match(/^\/v\/([^/]+)$/)) && request.method === "GET") {
    res = await view(m[1], url, env, now);
  } else if ((m = path.match(/^\/u\/([^/]+)$/))) {
    if (!ID.test(m[1])) res = text("This unsubscribe link isn't valid.", 404);
    else if (request.method === "POST") res = await unsubscribe(m[1], env, now);
    else if (request.method === "GET") res = unsubscribePage(m[1], env);
    else res = text("Method not allowed", 405);
  } else if (path === "/api/sync" && request.method === "GET") {
    res = (await authorised(request, env)) ? await pending(env) : text("Unauthorised", 401);
  } else if (path === "/api/ack" && request.method === "POST") {
    res = (await authorised(request, env)) ? await ack(request, env) : text("Unauthorised", 401);
  } else if (path.startsWith("/api/") || path.startsWith("/v/")) {
    res = text("Not found", 404);
  } else {
    res = await env.ASSETS.fetch(request);
  }
  return secure(res);
}

// ---- routes ----

async function view(slug, url, env, now) {
  if (ID.test(slug)) {
    // Only real demos count, so random slugs can't fill the store.
    const page = await env.ASSETS.fetch(new Request(`${url.origin}/${slug}/`));
    if (page.status === 200 && !(await env.EVENTS.get(`seen:${slug}`))) {
      const at = new Date(now).toISOString();
      await env.EVENTS.put(`view:${now}:${slug}`, "", { metadata: { slug, at } });
      await env.EVENTS.put(`seen:${slug}`, "1", { expirationTtl: SEEN_SECONDS });
    }
  }
  // Always the same tiny image, so the page looks the same whether or not the view counted.
  return new Response(GIF, { headers: { "content-type": "image/gif", "cache-control": "no-store" } });
}

async function unsubscribe(token, env, now) {
  const key = `unsub:${token}`;
  if (!(await env.EVENTS.get(key))) {
    await env.EVENTS.put(key, "1", { metadata: { token, at: new Date(now).toISOString() } });
  }
  return html(
    "Unsubscribed",
    `<h1>You're unsubscribed</h1><p>${esc(env.STUDIO || "We")} won't email you again. It can take up to a day to reach our list.</p>`,
  );
}

function unsubscribePage(token, env) {
  return html(
    "Unsubscribe",
    `<h1>Stop emails from ${esc(env.STUDIO || "us")}?</h1>
<form method="post" action="/u/${token}"><button type="submit">Unsubscribe</button></form>
<p>One click is enough. We won't ask why.</p>`,
  );
}

async function pending(env) {
  const views = [];
  const unsubscribes = [];
  for (const [prefix, out, field] of [["view:", views, "slug"], ["unsub:", unsubscribes, "token"]]) {
    const listed = await env.EVENTS.list({ prefix, limit: MAX_ITEMS });
    for (const k of listed.keys) {
      if (k.metadata && k.metadata[field]) out.push({ key: k.name, [field]: k.metadata[field], at: k.metadata.at });
    }
  }
  return json({ views, unsubscribes });
}

async function ack(request, env) {
  let body;
  try {
    body = await request.json();
  } catch {
    return text("Expected JSON", 400);
  }
  const keys = Array.isArray(body && body.keys) ? body.keys.slice(0, MAX_ITEMS) : [];
  let deleted = 0;
  for (const k of keys) {
    if (typeof k === "string" && (k.startsWith("view:") || k.startsWith("unsub:"))) {
      await env.EVENTS.delete(k);
      deleted += 1;
    }
  }
  return json({ deleted });
}

// ---- helpers ----

async function authorised(request, env) {
  const secret = env.SYNC_SECRET || "";
  const given = (request.headers.get("authorization") || "").replace(/^Bearer /, "");
  if (secret.length < 16) return false; // not set up: refuse rather than accept an empty secret
  // Compare digests, so the time taken says nothing about how much of the secret matched.
  const enc = new TextEncoder();
  const [a, b] = await Promise.all([crypto.subtle.digest("SHA-256", enc.encode(given)), crypto.subtle.digest("SHA-256", enc.encode(secret))]);
  const x = new Uint8Array(a);
  const y = new Uint8Array(b);
  let diff = 0;
  for (let i = 0; i < x.length; i++) diff |= x[i] ^ y[i];
  return diff === 0;
}

const hits = new Map(); // "kind|client|minute" -> count, this instance only
export function allow(kind, request, now) {
  const minute = Math.floor(now / 60000);
  const client = request.headers.get("cf-connecting-ip") || "-";
  const key = `${kind}|${client}|${minute}`;
  const n = (hits.get(key) || 0) + 1;
  hits.set(key, n);
  if (hits.size > 5000) {
    for (const k of hits.keys()) if (!k.endsWith(`|${minute}`)) hits.delete(k);
  }
  return n <= LIMITS[kind];
}
export function resetLimits() {
  hits.clear();
}

function secure(res) {
  const out = new Response(res.body, res);
  const h = out.headers;
  h.set("x-robots-tag", "noindex, nofollow");
  h.set("referrer-policy", "no-referrer");
  h.set("x-content-type-options", "nosniff");
  h.set("content-security-policy", "default-src 'none'; style-src 'unsafe-inline'; img-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'");
  h.delete("set-cookie");
  return out;
}

function text(body, status = 200) {
  return new Response(body, { status, headers: { "content-type": "text/plain; charset=utf-8" } });
}

function json(data) {
  return new Response(JSON.stringify(data), { headers: { "content-type": "application/json", "cache-control": "no-store" } });
}

function html(title, body) {
  return new Response(
    `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex"><title>${title}</title>
<style>body{font:17px/1.5 system-ui,sans-serif;max-width:32rem;margin:15vh auto;padding:0 16px;color:#1d1b18;background:#f7f5f0}
button{font:inherit;font-weight:600;padding:12px 22px;border:0;border-radius:10px;background:#1d1b18;color:#fff;cursor:pointer}</style>
</head><body>${body}</body></html>`,
    { headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" } },
  );
}

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}
