"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const projectRoot = path.resolve(__dirname, "..");
const engineSource = fs.readFileSync(
  path.join(projectRoot, "browser-extension/common/rule-engine.js"),
  "utf8",
);
const backgroundSource = fs.readFileSync(
  path.join(projectRoot, "browser-extension/background/service-worker.js"),
  "utf8",
);
const firefoxManifest = JSON.parse(
  fs.readFileSync(path.join(projectRoot, "browser-extension/manifest.json"), "utf8"),
);
const chromeManifest = JSON.parse(
  fs.readFileSync(path.join(projectRoot, "browser-extension/manifest.chrome.json"), "utf8"),
);
const failSafeRules = JSON.parse(
  fs.readFileSync(path.join(projectRoot, "browser-extension/rules/failsafe.json"), "utf8"),
);

for (const manifest of [firefoxManifest, chromeManifest]) {
  assert.equal(manifest.version, "0.2.2");
  assert.deepEqual(manifest.host_permissions, ["http://*/*", "https://*/*"]);
  assert.ok(
    manifest.web_accessible_resources.some((entry) =>
      entry.resources.includes("blocked/blocked.html"),
    ),
  );
}
assert.deepEqual(failSafeRules[0].action, {
  type: "redirect",
  redirect: { extensionPath: "/blocked/blocked.html" },
});

function eventHook() {
  return {
    listeners: [],
    addListener(listener) {
      this.listeners.push(listener);
    },
  };
}

function browserApi() {
  return {
    alarms: {
      created: [],
      create(name, options) {
        this.created.push([name, options]);
      },
      onAlarm: eventHook(),
    },
    declarativeNetRequest: {
      MAX_NUMBER_OF_DYNAMIC_RULES: 5000,
      async getDynamicRules() {
        return [];
      },
      async isRegexSupported() {
        return { isSupported: true };
      },
      async updateDynamicRules() {},
      async updateStaticRules() {},
    },
    runtime: {
      onInstalled: eventHook(),
      onStartup: eventHook(),
    },
    storage: {
      managed: {
        async get() {
          return {};
        },
      },
      onChanged: eventHook(),
    },
  };
}

function contextFor(apiName) {
  const api = browserApi();
  const context = vm.createContext({
    [apiName]: api,
    console: { error() {}, info() {} },
  });
  return { api, context };
}

{
  const { api, context } = contextFor("browser");
  vm.runInContext(engineSource, context, { filename: "common/rule-engine.js" });
  assert.equal(typeof context.importScripts, "undefined");
  vm.runInContext(backgroundSource, context, { filename: "background/service-worker.js" });
  assert.equal(api.runtime.onStartup.listeners.length, 1);
  assert.equal(api.alarms.created.length, 1);
}

{
  const { api, context } = contextFor("chrome");
  const imports = [];
  context.importScripts = (source) => {
    imports.push(source);
    vm.runInContext(engineSource, context, { filename: "common/rule-engine.js" });
  };
  vm.runInContext(backgroundSource, context, { filename: "background/service-worker.js" });
  assert.deepEqual(imports, ["../common/rule-engine.js"]);
  assert.equal(api.runtime.onStartup.listeners.length, 1);
  assert.equal(api.alarms.created.length, 1);
}

console.log("Firefox- und Chrome-Hintergrundstart erfolgreich getestet.");
