"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

vm.runInThisContext(fs.readFileSync(path.join(__dirname, "..", "browser-extension", "options", "order-model.js"), "utf8"));
const { sortedBlocks, moveBlock, prioritiesForOrder } = globalThis.UPC_ORDER_MODEL;
const blocks = [{ id: "low", priority: -4 }, { id: "first-tie", priority: 8 }, { id: "second-tie", priority: 8 }];
assert.deepEqual(sortedBlocks(blocks).map((block) => block.id), ["first-tie", "second-tie", "low"]);
const moved = moveBlock(blocks, "low", -2);
assert.deepEqual(moved.map((block) => block.id), ["low", "first-tie", "second-tie"]);
assert.deepEqual(prioritiesForOrder(moved), [{ id: "low", priority: 1 }, { id: "first-tie", priority: 0 }, { id: "second-tie", priority: -1 }]);
console.log("Prioritätsmodell erfolgreich getestet.");
