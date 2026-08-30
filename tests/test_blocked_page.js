"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "..", "browser-extension", "blocked", "blocked.js"),
  "utf8",
);

async function main() {
  const elements = {
    "#block-source": { hidden: true },
    "#block-source-name": { textContent: "" },
    "#block-source-priority": { textContent: "" },
  };
  let sentMessage = null;
  const context = vm.createContext({
    browser: {
      runtime: {
        async sendMessage(message) {
          sentMessage = message;
          return { ok: true, result: { name: "Soziale Medien", priority: 50 } };
        },
      },
    },
    document: { querySelector(selector) { return elements[selector]; } },
    location: { search: "?block=social-media" },
    URLSearchParams,
  });
  vm.runInContext(source, context, { filename: "blocked/blocked.js" });
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(
    JSON.parse(JSON.stringify(sentMessage)),
    { type: "get_block_info", block_id: "social-media" },
  );
  assert.equal(elements["#block-source-name"].textContent, "Soziale Medien");
  assert.equal(elements["#block-source-priority"].textContent, "Priorität 50");
  assert.equal(elements["#block-source"].hidden, false);
  console.log("Blockquellen-Anzeige erfolgreich getestet.");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
