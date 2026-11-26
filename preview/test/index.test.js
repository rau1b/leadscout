// Offline tests for the preview Worker: a fake KV store and fake static assets, no Cloudflare.
import { beforeEach, describe, expect, it } from "vitest";
import { handle, resetLimits } from "../src/index.js";

const SLUG = "AbCdEfGhIjKlMnOpQrStUv"; // 22 characters, like secrets.token_urlsafe(16)
const TOKEN = "tOkEnTokenToken_123-xyz";
const SECRET = "s3cret-s3cret-s3cret-s3cret";
const T0 = Date.parse("2026-11-26T10:00:00Z");

function fakeKV() {
  const data = new Map(); // key -> {value, metadata, expires}
  return {
    data,
    async get(key) {
      return data.get(key)?.value ?? null;
    },
    async put(key, value, opts = {}) {
      data.set(key, { value, metadata: opts.metadata, ttl: opts.expirationTtl });
    },
    async delete(key) {
      data.delete(key);
    },
    async list({ prefix = "", limit = 1000 } = {}) {
      const keys = [...data.keys()].filter((k) => k.startsWith(prefix)).sort().slice(0, limit);
      return { keys: keys.map((name) => ({ name, metadata: data.get(name).metadata })), list_complete: true };
    },
  };
}

function fakeAssets(slugs) {
  return {
    async fetch(req) {
      const path = new URL(req.url).pathname;
      const hit = path === "/" || slugs.some((s) => path === `/${s}/`);
      return new Response(hit ? "<html>page</html>" : "Not found", { status: hit ? 200 : 404, headers: { "content-type": "text/html" } });
    },
  };
}

let env;
beforeEach(() => {
  resetLimits();
  env = { EVENTS: fakeKV(), ASSETS: fakeAssets([SLUG]), SYNC_SECRET: SECRET, STUDIO: "Kite Studio" };
});

const get = (path, headers = {}, now = T0) => handle(new Request(`https://demo.example.in${path}`, { headers }), env, now);
const post = (path, body, headers = {}, now = T0) =>
  handle(new Request(`https://demo.example.in${path}`, { method: "POST", body, headers }), env, now);
const auth = { authorization: `Bearer ${SECRET}` };

describe("static pages", () => {
  it("serves a demo with noindex and no cookies", async () => {
    const res = await get(`/${SLUG}/`);
    expect(res.status).toBe(200);
    expect(res.headers.get("x-robots-tag")).toBe("noindex, nofollow");
    expect(res.headers.get("referrer-policy")).toBe("no-referrer");
    expect(res.headers.get("set-cookie")).toBeNull();
  });

  it("404s for pages that were never published or were taken down, still with noindex", async () => {
    const res = await get("/someOtherSlugThatIsGone12/");
    expect(res.status).toBe(404);
    expect(res.headers.get("x-robots-tag")).toBe("noindex, nofollow");
  });
});

describe("view ping", () => {
  it("records slug and time only, once per 30 minutes", async () => {
    const res = await get(`/v/${SLUG}`, { "cf-connecting-ip": "203.0.113.9" });
    expect(res.headers.get("content-type")).toBe("image/gif");
    await get(`/v/${SLUG}`, {}, T0 + 60_000); // a reload a minute later
    const views = [...env.EVENTS.data.entries()].filter(([k]) => k.startsWith("view:"));
    expect(views).toHaveLength(1);
    expect(views[0][1].metadata).toEqual({ slug: SLUG, at: "2026-11-26T10:00:00.000Z" });
    expect(JSON.stringify([...env.EVENTS.data.entries()])).not.toContain("203.0.113.9"); // no IP stored anywhere
    expect(env.EVENTS.data.get(`seen:${SLUG}`).ttl).toBe(1800);
  });

  it("ignores slugs that aren't published pages", async () => {
    const res = await get("/v/NotARealDemoSlug_abcdef");
    expect(res.status).toBe(200); // same image either way
    await get("/v/../../etc");
    expect(env.EVENTS.data.size).toBe(0);
  });
});

describe("unsubscribe", () => {
  it("GET shows a confirm button and records nothing", async () => {
    const res = await get(`/u/${TOKEN}`);
    const body = await res.text();
    expect(body).toContain(`<form method="post" action="/u/${TOKEN}">`);
    expect(body).toContain("Kite Studio");
    expect(env.EVENTS.data.size).toBe(0);
  });

  it("POST records token and time; RFC 8058 one-click works; repeats are one record", async () => {
    const res = await post(`/u/${TOKEN}`, "List-Unsubscribe=One-Click", { "content-type": "application/x-www-form-urlencoded" });
    expect(res.status).toBe(200);
    await post(`/u/${TOKEN}`, "", {}, T0 + 5000);
    expect([...env.EVENTS.data.keys()]).toEqual([`unsub:${TOKEN}`]);
    expect(env.EVENTS.data.get(`unsub:${TOKEN}`).metadata).toEqual({ token: TOKEN, at: "2026-11-26T10:00:00.000Z" });
  });

  it("rejects malformed tokens", async () => {
    expect((await post("/u/short", "")).status).toBe(404);
    expect(env.EVENTS.data.size).toBe(0);
  });

  it("escapes the studio name", async () => {
    env.STUDIO = "<script>x</script>";
    expect(await (await get(`/u/${TOKEN}`)).text()).not.toContain("<script>x");
  });
});

describe("sync API", () => {
  it("needs the bearer secret", async () => {
    expect((await get("/api/sync")).status).toBe(401);
    expect((await get("/api/sync", { authorization: "Bearer wrong-wrong-wrong-wrong" })).status).toBe(401);
    env.SYNC_SECRET = "";
    expect((await get("/api/sync", { authorization: "Bearer " })).status).toBe(401); // unset secret never matches
  });

  it("hands over views and unsubscribes, and deletes only what LeadScout acknowledged", async () => {
    await get(`/v/${SLUG}`);
    await post(`/u/${TOKEN}`, "");
    const data = await (await get("/api/sync", auth)).json();
    expect(data.views).toEqual([{ key: `view:${T0}:${SLUG}`, slug: SLUG, at: "2026-11-26T10:00:00.000Z" }]);
    expect(data.unsubscribes).toEqual([{ key: `unsub:${TOKEN}`, token: TOKEN, at: "2026-11-26T10:00:00.000Z" }]);

    const acked = await (await post("/api/ack", JSON.stringify({ keys: [data.views[0].key, `seen:${SLUG}`, "other"] }), auth)).json();
    expect(acked).toEqual({ deleted: 1 }); // only view:/unsub: keys can be deleted
    const again = await (await get("/api/sync", auth)).json();
    expect(again.views).toEqual([]);
    expect(again.unsubscribes).toHaveLength(1); // not acknowledged yet, so still there
  });

  it("ack needs the secret too", async () => {
    await post(`/u/${TOKEN}`, "");
    expect((await post("/api/ack", JSON.stringify({ keys: [`unsub:${TOKEN}`] }))).status).toBe(401);
    expect(env.EVENTS.data.size).toBe(1);
  });
});

describe("rate limits", () => {
  it("caps each route per minute", async () => {
    const statuses = [];
    for (let i = 0; i < 12; i++) statuses.push((await post(`/u/${TOKEN}`, "", { "cf-connecting-ip": "198.51.100.7" })).status);
    expect(statuses.slice(0, 10).every((s) => s === 200)).toBe(true);
    expect(statuses.slice(10)).toEqual([429, 429]);
    expect((await post(`/u/${TOKEN}`, "", { "cf-connecting-ip": "198.51.100.7" }, T0 + 61_000)).status).toBe(200); // next minute
  });
});
