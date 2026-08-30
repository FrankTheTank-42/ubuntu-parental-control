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
const optionsHtml = fs.readFileSync(
  path.join(projectRoot, "browser-extension/options/options.html"),
  "utf8",
);
const optionsSource = fs.readFileSync(
  path.join(projectRoot, "browser-extension/options/options.js"),
  "utf8",
);

assert.ok(optionsHtml.includes('id="busy-overlay"'));
assert.ok(optionsHtml.includes('id="connection-error-detail"'));
assert.ok(optionsHtml.includes('id="repair-native"'));
assert.ok(optionsHtml.includes('ubuntu-parental-control://firefox-consent/allow'));
assert.ok(optionsHtml.includes('class="add-domain-unavailable"'));
assert.ok(optionsHtml.includes('class="schedule-editor wide"'));
assert.ok(optionsHtml.includes('id="overview-view"'));
assert.ok(optionsHtml.includes('id="detail-view"'));
assert.ok(optionsHtml.includes('id="profile-form"'));
assert.ok(optionsHtml.includes('id="draft-bar"'));
assert.ok(optionsHtml.includes('id="save-all"'));
assert.ok(optionsHtml.includes('id="discard-draft"'));
assert.ok(optionsHtml.includes('draggable="false"'));
assert.ok(optionsHtml.includes('class="admin-schedule-timezone"'));
assert.ok(optionsHtml.includes('class="secondary add-window"'));
assert.ok(optionsHtml.includes('<script src="schedule-model.js"></script>'));
assert.ok(optionsHtml.includes('<script src="order-model.js"></script>'));
assert.ok(!optionsHtml.includes('class="admin-schedule"'));
assert.ok(!optionsHtml.includes("admin-child-add"));
assert.ok(optionsSource.includes('form.classList.add("locked")'));
assert.ok(optionsSource.includes('document.body.classList.add(admin ? "mode-parent"'));
assert.ok(optionsSource.includes('title: "Native Host nicht erreichbar"'));
assert.ok(optionsSource.includes('if (child && block.action === "block")'));
assert.ok(optionsSource.includes("scheduleFromDrafts(timezone, drafts)"));
assert.ok(optionsSource.includes('form.querySelector(".schedule-empty").hidden'));
assert.ok(optionsSource.includes('event.altKey'));
assert.ok(optionsSource.includes('draftRules.profile.default_action ='));
assert.ok(optionsSource.includes('applyAdminRules(structuredClone(draftRules)'));
assert.ok(optionsSource.includes('targets: { domains: [], url_patterns: [], url_regex: [] }'));
assert.ok(!optionsSource.includes('prompt("Erste zu blockierende Domain:")'));
assert.ok(backgroundSource.includes("Domain fehlt im bestätigten Regelsnapshot"));

for (const manifest of [firefoxManifest, chromeManifest]) {
  assert.equal(manifest.version, "0.5.1");
  assert.deepEqual(manifest.host_permissions, ["http://*/*", "https://*/*"]);
  assert.ok(manifest.permissions.includes("contextMenus"));
  assert.ok(manifest.permissions.includes("nativeMessaging"));
  assert.equal(manifest.options_ui.page, "options/options.html");
  assert.equal(manifest.action.default_title, "Ubuntu Parental Control – Regelverwaltung öffnen");
  for (const size of [16, 32, 48, 64, 128]) {
    assert.equal(manifest.icons[String(size)], `icons/icon-${size}.png`);
    assert.equal(manifest.action.default_icon[String(size)], `icons/icon-${size}.png`);
    assert.ok(fs.existsSync(path.join(projectRoot, "browser-extension", `icons/icon-${size}.png`)));
  }
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
assert.equal(chromeManifest.icons["128"], "icons/icon-128.png");

function eventHook() {
  return {
    listeners: [],
    addListener(listener) {
      this.listeners.push(listener);
    },
  };
}

function browserApi() {
  const nativePort = {
    onMessage: eventHook(),
    onDisconnect: eventHook(),
    posted: [],
    postMessage(message) {
      this.posted.push(message);
    },
  };
  return {
    action: { onClicked: eventHook() },
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
    contextMenus: {
      created: [],
      async removeAll() { this.created = []; },
      create(item) { this.created.push(item); },
      onClicked: eventHook(),
    },
    runtime: {
      lastError: null,
      nativePort,
      getURL(pathname) { return `moz-extension://test/${pathname}`; },
      async openOptionsPage() {},
      connectNative(name) {
        assert.equal(name, "ubuntu_parental_control");
        return nativePort;
      },
      onMessage: eventHook(),
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
    tabs: { async create() {}, async query() { return []; }, async reload() {} },
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
  assert.equal(api.contextMenus.onClicked.listeners.length, 1);
  assert.equal(api.action.onClicked.listeners.length, 1);
  assert.equal(api.runtime.nativePort.onMessage.listeners.length, 0);
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
  assert.equal(api.action.onClicked.listeners.length, 1);
  assert.equal(api.alarms.created.length, 1);
  assert.equal(api.runtime.nativePort.onMessage.listeners.length, 0);
}

console.log("Firefox- und Chrome-Hintergrundstart erfolgreich getestet.");
