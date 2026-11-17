// Unit tests for the app shell's navigation helpers. Run with `pnpm test` (node:test).
import assert from "node:assert/strict";
import { test } from "node:test";

import { activeNav, ADMIN_HREF, countHint, healthLine, NAV_ITEMS, navItems } from "./nav.ts";

test("the Admin item is listed only for an admin, last, linking to /app/admin", () => {
  assert.deepEqual(navItems(false), NAV_ITEMS);
  assert.equal(navItems(false).some((i) => i.id === "admin"), false);
  const admin = navItems(true);
  assert.equal(admin.length, NAV_ITEMS.length + 1);
  assert.deepEqual(admin.at(-1), { id: "admin", label: "Admin", href: "/app/admin" });
  assert.equal(ADMIN_HREF, "/app/admin");
});

test("/app/admin highlights Admin; other /app pages stay under Home", () => {
  assert.equal(activeNav("/app/admin"), "admin");
  assert.equal(activeNav("/app/admin/"), "admin");
  assert.equal(activeNav("/app/account"), "home");
  assert.equal(activeNav("/app/administer"), "home");
});

test("each top-level route highlights its own item", () => {
  assert.equal(activeNav("/app"), "home");
  assert.equal(activeNav("/match"), "match");
  assert.equal(activeNav("/runs"), "runs");
  assert.equal(activeNav("/trials"), "trials");
  assert.equal(activeNav("/eval"), "eval");
});

test("detail routes highlight their parent item", () => {
  assert.equal(activeNav("/match/run-123"), "match");
  assert.equal(activeNav("/runs/run-123"), "runs");
  assert.equal(activeNav("/feasibility/NCT01234567"), "trials");
  assert.equal(activeNav("/closer/run-456"), "match");
});

test("a trailing slash still matches, a lookalike prefix does not", () => {
  assert.equal(activeNav("/runs/"), "runs");
  assert.equal(activeNav("/app/"), "home");
  assert.equal(activeNav("/apps"), null);
  assert.equal(activeNav("/matches"), null);
  assert.equal(activeNav("/evaluation"), null);
});

test("the bare marketing page at / highlights nothing", () => {
  assert.equal(activeNav("/"), null);
});

test("an unknown route highlights nothing", () => {
  assert.equal(activeNav("/nope"), null);
  assert.equal(activeNav(null), null);
});

test("count hint shows the count, or cap+ when the list was cut off at the cap", () => {
  assert.equal(countHint(0, 200), "0");
  assert.equal(countHint(37, 200), "37");
  assert.equal(countHint(200, 200), "200+");
  assert.equal(countHint(null, 200), null);
});

test("health line: healthy, not ready, unreachable, each with its mode", () => {
  assert.deepEqual(healthLine({ ok: true, demo_mode: "off", model_ids: {}, demo_patients: [] }, null), {
    tone: "ok",
    text: "API healthy · live mode",
  });
  assert.deepEqual(healthLine({ ok: true, demo_mode: "replay", model_ids: {}, demo_patients: [] }, null), {
    tone: "ok",
    text: "API healthy · replay mode",
  });
  assert.deepEqual(healthLine({ ok: false, demo_mode: "replay", model_ids: {}, demo_patients: [] }, null), {
    tone: "warn",
    text: "API not ready · replay mode",
  });
  assert.deepEqual(healthLine(null, "fetch failed"), { tone: "down", text: "API unreachable" });
});

test("health line is unknown while the first check is in flight", () => {
  assert.equal(healthLine(null, null), null);
});
