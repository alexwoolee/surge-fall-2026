import test from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { InvestigationScope } from "../components/meshmind/investigation-scope";
import { configuredWorkers, isWorkerId } from "./workers";
import type { ControlConfig } from "./types";

const config: ControlConfig = { mode: "execute", canStart: true, notice: "Location and dates resolve from the request.", case: { case_id: "default", name: "Default case only", bbox: {}, requested_window: { start: "2019-07-28", end: "2019-08-01" } }, routingMode: "prompt", availableWorkers: ["hydro", "flood", "dam"], examples: ["Review Toddbrook Reservoir in June 2007.", "Review Toddbrook Reservoir in July 2019."] };

test("prompt guidance displays examples and conditional scope without constraining requests to the default case", () => {
  const html = renderToStaticMarkup(createElement(InvestigationScope, { config, compact: false, busy: false, onExample: () => assert.fail("Rendering must not submit a request") }));
  assert.match(html, /Choose a location and date range/);
  assert.match(html, /June 2007/); assert.match(html, /July 2019/);
  assert.match(html, /joins only for Toddbrook Reservoir, Whaley Bridge, Derbyshire/);
  assert.match(html, /historical date/); assert.match(html, /query available observations at runtime/);
  assert.doesNotMatch(html, /Default case only|must use this configured/);
  assert.equal((html.match(/type="button"/g) || []).length, 2);
  const legacy = renderToStaticMarkup(createElement(InvestigationScope, { config: { ...config, routingMode: undefined }, compact: false, busy: false, onExample: () => {} }));
  assert.match(legacy, /Default case only/); assert.match(legacy, /must use this configured/);
});

test("worker navigation adds Dam only when configured; route roles remain a strict allowlist", () => {
  assert.deepEqual(configuredWorkers(null), ["hydro", "flood"]);
  assert.deepEqual(configuredWorkers({ ...config, availableWorkers: undefined }), ["hydro", "flood"]);
  assert.deepEqual(configuredWorkers(config), ["hydro", "flood", "dam"]);
  assert.equal(isWorkerId("dam"), true);
  for (const value of ["DAM", "other", "dam/../flood", null, "__proto__"]) assert.equal(isWorkerId(value), false);
});
