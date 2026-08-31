"use strict";

const assert = require("node:assert/strict");
const cryptoModule = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

if (!globalThis.crypto) globalThis.crypto = cryptoModule.webcrypto;
const projectRoot = path.resolve(__dirname, "..");
vm.runInThisContext(
  fs.readFileSync(path.join(projectRoot, "browser-extension/common/rule-engine.js"), "utf8"),
  { filename: "rule-engine.js" },
);

const engine = globalThis.UPC_RULE_ENGINE;

function matchers(domains = [], urlPatterns = [], urlRegex = []) {
  return { domains, url_patterns: urlPatterns, url_regex: urlRegex };
}

function block(id, priority, action, targets, exceptions = matchers()) {
  return { id, enabled: true, priority, action, targets, exceptions };
}

function rules(blocks, defaultAction = "allow") {
  return {
    format_version: "1.0",
    profile: {
      timezone: "Europe/Berlin",
      default_action: defaultAction,
      conflict_policy: "priority_then_deny",
    },
    blocks,
  };
}

assert.equal(
  engine.patternToRegex("*://reddit.com/r/gaming/*"),
  "^https?:\\/\\/reddit\\.com(?::[0-9]+)?/r/gaming/.*$",
);

const overnight = {
  start: "22:00",
  end: "02:00",
  rrule: "FREQ=WEEKLY;BYDAY=MO",
};
assert.equal(engine.windowIsActive(overnight, { day: "MO", minutes: 23 * 60 }), true);
assert.equal(engine.windowIsActive(overnight, { day: "TU", minutes: 60 }), true);
assert.equal(engine.windowIsActive(overnight, { day: "TU", minutes: 3 * 60 }), false);

const compiled = engine.compile(
  rules([
    block("allow-high", 1, "allow", matchers(["school.example"])),
    block("allow-tie", 0, "allow", matchers(["same.example"])),
    block(
      "block-tie",
      0,
      "block",
      matchers(["same.example", "video.example"]),
      matchers(["education.video.example"]),
    ),
  ]),
  new Date("2026-08-26T12:00:00Z"),
);
assert.equal(compiled.rules.length, 4);
const allowHigh = compiled.rules.find((rule) => rule.condition.requestDomains[0] === "school.example");
const allowTie = compiled.rules.find(
  (rule) => rule.action.type === "allow" && rule.condition.requestDomains[0] === "same.example",
);
const blockTie = compiled.rules.find(
  (rule) => rule.action.type === "redirect" && rule.condition.requestDomains[0] === "same.example",
);
assert.ok(allowHigh.priority > blockTie.priority);
assert.ok(blockTie.priority > allowTie.priority);
assert.equal(
  blockTie.action.redirect.extensionPath,
  "/blocked/blocked.html?block=block-tie",
);
assert.deepEqual(blockTie.condition.excludedRequestDomains, ["education.video.example"]);

const absoluteRedirect = engine.compile(
  rules([block("named-block", 0, "block", matchers(["named.example"]))]),
  new Date(),
  "moz-extension://test/blocked/blocked.html",
).rules[0];
assert.equal(
  absoluteRedirect.action.redirect.url,
  "moz-extension://test/blocked/blocked.html?block=named-block",
);

const patternRule = engine.compile(
  rules([block("pattern", 0, "block", matchers([], ["*://example.com/Case/*"]))]),
  new Date(),
).rules[0];
assert.equal(patternRule.condition.isUrlFilterCaseSensitive, true);

const preparedBlocklist = engine.compile(
  rules([block("prepared", 0, "block", matchers())]),
  new Date(),
);
assert.deepEqual(preparedBlocklist.rules, []);
assert.equal(preparedBlocklist.defaultAction, "allow");

const sameNameBlocks = [
  { ...block("streaming", 0, "block", matchers(["one.example"])), name: "Streaming" },
  { ...block("streaming-2", 0, "block", matchers(["two.example"])), name: "Streaming" },
];
assert.equal(engine.compile(rules(sameNameBlocks), new Date()).rules.length, 2);
assert.deepEqual(
  engine
    .compile(rules(sameNameBlocks.filter((item) => item.id !== "streaming-2")), new Date())
    .rules.map((rule) => rule.condition.requestDomains[0]),
  ["one.example"],
);

assert.throws(
  () =>
    engine.compile(
      rules([
        block(
          "unsafe-exception",
          0,
          "block",
          matchers(["example.com"]),
          matchers([], ["*://example.com/allowed/*"]),
        ),
      ]),
      new Date(),
    ),
  /nicht verlustfrei/,
);

(async () => {
  const managedRules = rules([]);
  const canonical = engine.stableStringify(managedRules);
  const revision = cryptoModule.createHash("sha256").update(canonical).digest("hex");
  const snapshot = { protocol_version: 2, generation: 7, revision, rules: managedRules };
  const parsed = await engine.parseManagedSnapshot({
    protocol_version: 2,
    generation: 7,
    revision,
    snapshot_json: engine.stableStringify(snapshot),
  });
  assert.equal(parsed.revision, revision);
  assert.equal(parsed.generation, 7);
  console.log("Browserneutrale Regelengine erfolgreich getestet.");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
