"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const projectRoot = path.resolve(__dirname, "..");
vm.runInThisContext(
  fs.readFileSync(
    path.join(projectRoot, "browser-extension/options/schedule-model.js"),
    "utf8",
  ),
  { filename: "schedule-model.js" },
);

const model = globalThis.UPC_SCHEDULE_MODEL;

assert.deepEqual(
  [...model.parseRrule("FREQ=WEEKLY;BYDAY=MO,WE,FR")],
  ["MO", "WE", "FR"],
);
assert.throws(
  () => model.parseRrule("FREQ=WEEKLY;BYDAY=MO,MO"),
  /ungültige oder doppelte/,
);

assert.equal(model.scheduleFromDrafts("Europe/Berlin", []), null);
assert.deepEqual(
  model.scheduleFromDrafts(" Europe/Berlin ", [
    { days: ["FR", "MO", "WE"], start: "18:00", end: "20:00" },
    { days: ["SA", "SU"], start: "22:00", end: "07:00" },
  ]),
  {
    timezone: "Europe/Berlin",
    windows: [
      { start: "18:00", end: "20:00", rrule: "FREQ=WEEKLY;BYDAY=MO,WE,FR" },
      { start: "22:00", end: "07:00", rrule: "FREQ=WEEKLY;BYDAY=SA,SU" },
    ],
  },
);
assert.throws(
  () => model.scheduleFromDrafts("Europe/Berlin", [
    { days: [], start: "18:00", end: "20:00" },
  ]),
  /mindestens einen Wochentag/,
);
assert.throws(
  () => model.scheduleFromDrafts("Europe/Berlin", [
    { days: ["MO"], start: "25:00", end: "20:00" },
  ]),
  /Start- und Endzeit/,
);
assert.throws(
  () => model.scheduleFromDrafts("Europe/Berlin", [
    { days: ["MO"], start: "18:00", end: "20:00" },
    { days: ["MO"], start: "18:00", end: "20:00" },
  ]),
  /nicht doppelt/,
);

console.log("Zeitfenster-Modell erfolgreich getestet.");
