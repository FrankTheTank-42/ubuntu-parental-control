"use strict";

const assert = require("node:assert/strict");
const cryptoModule = require("node:crypto");
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

function hook() {
  return {
    listeners: [],
    addListener(listener) { this.listeners.push(listener); },
  };
}

function stableStringify(value) {
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value).sort().map((key) =>
      `${JSON.stringify(key)}:${stableStringify(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

function managed(rules, publicKeySpki) {
  const revision = cryptoModule.createHash("sha256").update(stableStringify(rules)).digest("hex");
  return {
    protocol_version: 1,
    revision,
    snapshot_json: JSON.stringify({ protocol_version: 1, revision, rules }),
    live_public_key_spki: publicKeySpki,
  };
}

async function signedManaged(rulesValue, keyPair, publicKeySpki) {
  const value = managed(rulesValue, publicKeySpki);
  const signature = await cryptoModule.webcrypto.subtle.sign(
    { name: "ECDSA", hash: "SHA-256" },
    keyPair.privateKey,
    new TextEncoder().encode(value.snapshot_json),
  );
  value.live_signature = Buffer.from(signature).toString("base64");
  return value;
}

function rules(domains) {
  return {
    format_version: "1.0",
    profile: {
      timezone: "Europe/Berlin",
      default_action: "allow",
      conflict_policy: "priority_then_deny",
    },
    blocks: [{
      id: "self-blocked-sites",
      name: "Eigene Ablenkungen",
      enabled: true,
      priority: 0,
      action: "block",
      user_permissions: {
        add_domains: true,
        remove_domains: false,
        add_url_patterns: false,
        add_url_regex: false,
        modify_exceptions: false,
        modify_schedule: false,
        disable_block: false,
      },
      targets: { domains, url_patterns: [], url_regex: [] },
      exceptions: { domains: [], url_patterns: [], url_regex: [] },
      limits: null,
    }],
  };
}

async function main() {
  const keyPair = await cryptoModule.webcrypto.subtle.generateKey(
    { name: "ECDSA", namedCurve: "P-256" },
    true,
    ["sign", "verify"],
  );
  const publicKeySpki = Buffer.from(
    await cryptoModule.webcrypto.subtle.exportKey("spki", keyPair.publicKey),
  ).toString("base64");
  let statusSigningKey = keyPair.privateKey;
  let statusRestricted = true;
  let adminRequestCount = 0;
  const nativePort = {
    onMessage: hook(),
    onDisconnect: hook(),
    async postMessage(request) {
      const respond = (result) => {
        for (const listener of this.onMessage.listeners) {
          listener({ id: request.id, ok: true, result });
        }
      };
      if (request.command === "base_rules") {
        respond({
          rules: rules(["example.com"]),
          user_domains: { format_version: 1, users: {} },
        });
        return;
      }
      if (request.command === "own_user_domains") {
        respond({
          user_domains: {
            format_version: 1,
            users: { "1001": { "self-blocked-sites": ["child.example"] } },
          },
        });
        return;
      }
      if (request.command === "add_domain") {
        respond({
          block_id: request.block_id,
          domain: request.domain,
          managed: await signedManaged(
            rules(["example.com", request.domain]),
            keyPair,
            publicKeySpki,
          ),
        });
        return;
      }
      if (request.command === "admin_apply") {
        adminRequestCount += 1;
        respond({
          applied: true,
          managed: await signedManaged(request.rules, keyPair, publicKeySpki),
        });
        return;
      }
      if (request.command !== "status") return;
      const authorizationJson = JSON.stringify({
        protocol_version: 1,
        nonce: request.nonce,
        uid: 1001,
        restricted: statusRestricted,
        can_add_domains_to: statusRestricted ? ["self-blocked-sites"] : [],
      });
      const signature = await cryptoModule.webcrypto.subtle.sign(
        { name: "ECDSA", hash: "SHA-256" },
        statusSigningKey,
        new TextEncoder().encode(authorizationJson),
      );
      respond({
        authorization_json: authorizationJson,
        authorization_signature: Buffer.from(signature).toString("base64"),
      });
    },
  };
  let dynamicRules = [];
  const createdContextMenus = [];
  const createdTabs = [];
  const reloadedTabs = [];
  let optionsPageOpenCount = 0;
  let currentManaged = managed(rules(["example.com"]), publicKeySpki);
  const api = {
    alarms: { create() {}, onAlarm: hook() },
    declarativeNetRequest: {
      MAX_NUMBER_OF_DYNAMIC_RULES: 5000,
      async getDynamicRules() { return dynamicRules; },
      async isRegexSupported() { return { isSupported: true }; },
      async updateDynamicRules(update) { dynamicRules = update.addRules; },
      async updateStaticRules() {},
    },
    contextMenus: {
      async removeAll() { createdContextMenus.length = 0; },
      create(item) { createdContextMenus.push(item); },
      onClicked: hook(),
    },
    action: { onClicked: hook() },
    runtime: {
      lastError: null,
      connectNative() { return nativePort; },
      getURL(pathname) { return `moz-extension://test/${pathname}`; },
      async openOptionsPage() { optionsPageOpenCount += 1; },
      onInstalled: hook(),
      onStartup: hook(),
      onMessage: hook(),
    },
    storage: {
      managed: { async get() { return currentManaged; } },
      onChanged: hook(),
    },
    tabs: {
      async create(options) { createdTabs.push(options); },
      async query(options) {
        assert.deepEqual(Array.from(options.url), [
          "*://new-child.example/*",
          "*://*.new-child.example/*",
        ]);
        return [{ id: 71 }, { id: 72 }, { id: 71 }];
      },
      async reload(tabId) {
        assert.ok(
          dynamicRules.some((rule) =>
            rule.condition.requestDomains?.includes("new-child.example"),
          ),
          "DNR-Regel muss vor dem Neuladen aktiv sein",
        );
        reloadedTabs.push(tabId);
      },
    },
  };
  const scheduledTimeouts = [];
  const context = vm.createContext({
    browser: api,
    console: { error() {}, info() {} },
    crypto: cryptoModule.webcrypto,
    TextEncoder,
    URL,
    atob,
    setTimeout(callback, milliseconds) {
      scheduledTimeouts.push(milliseconds);
      return setTimeout(callback, milliseconds);
    },
    clearTimeout,
  });
  vm.runInContext(engineSource, context, { filename: "common/rule-engine.js" });
  vm.runInContext(backgroundSource, context, { filename: "background/service-worker.js" });
  await new Promise((resolve) => setTimeout(resolve, 30));
  assert.equal(dynamicRules.length, 1);
  assert.equal(dynamicRules[0].condition.requestDomains.join(","), "example.com");
  assert.equal(nativePort.onMessage.listeners.length, 0);
  assert.equal(createdContextMenus.length, 3);
  assert.equal(createdContextMenus[0].id, "upc-open-rule-management");
  assert.deepEqual(Array.from(createdContextMenus[0].contexts), ["action"]);
  assert.equal(createdContextMenus[2].icons["16"], "icons/icon-16.png");

  const contextMenuClick = api.contextMenus.onClicked.listeners[0];
  contextMenuClick({
    menuItemId: "upc-add-current-domain:self-blocked-sites",
    pageUrl: "https://WWW.Example.NET/watch?v=1",
  });
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(createdTabs.length, 1);
  assert.match(createdTabs[0].url, /context_block=self-blocked-sites/);
  assert.match(createdTabs[0].url, /context_domain=www.example.net/);
  assert.equal(nativePort.onMessage.listeners.length, 0);

  contextMenuClick({ menuItemId: "upc-open-rule-management" });
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(optionsPageOpenCount, 1);
  api.action.onClicked.listeners[0]();
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(optionsPageOpenCount, 2);

  const runtimeMessage = api.runtime.onMessage.listeners[0];
  const uiState = await new Promise((resolve) => {
    runtimeMessage({ type: "get_ui_state" }, null, resolve);
  });
  assert.equal(uiState.ok, true);
  assert.equal(nativePort.onMessage.listeners.length, 1);
  assert.equal(uiState.result.native.status.restricted, true);
  assert.deepEqual(
    Array.from(uiState.result.user_domains.users["1001"]["self-blocked-sites"]),
    ["child.example"],
  );
  assert.deepEqual(
    Array.from(uiState.result.native.status.can_add_domains_to),
    ["self-blocked-sites"],
  );
  const childAddition = await new Promise((resolve) => {
    runtimeMessage({
      type: "add_domain",
      block_id: "self-blocked-sites",
      domain: "new-child.example",
    }, null, resolve);
  });
  assert.equal(childAddition.ok, true);
  assert.equal(dynamicRules.length, 2);
  assert.equal(dynamicRules[1].condition.requestDomains.join(","), "new-child.example");
  assert.deepEqual(reloadedTabs, [71, 72]);
  assert.equal(childAddition.result.reloaded_tabs, 2);
  const rejectedAdminEdit = await new Promise((resolve) => {
    runtimeMessage({ type: "admin_apply", rules: rules([]) }, null, resolve);
  });
  assert.equal(rejectedAdminEdit.ok, false);
  assert.match(rejectedAdminEdit.error, /nicht freigeschaltet/);

  const wrongStatusKeyPair = await cryptoModule.webcrypto.subtle.generateKey(
    { name: "ECDSA", namedCurve: "P-256" },
    true,
    ["sign", "verify"],
  );
  statusSigningKey = wrongStatusKeyPair.privateKey;
  const rejectedUiState = await new Promise((resolve) => {
    runtimeMessage({ type: "get_ui_state" }, null, resolve);
  });
  assert.equal(rejectedUiState.ok, true);
  assert.equal(rejectedUiState.result.native.status, null);
  assert.match(rejectedUiState.result.native.error, /Berechtigungssignatur/);
  statusSigningKey = keyPair.privateKey;

  statusRestricted = false;
  const parentUiState = await new Promise((resolve) => {
    runtimeMessage({ type: "get_ui_state" }, null, resolve);
  });
  assert.equal(parentUiState.ok, true);
  assert.equal(parentUiState.result.native.status.restricted, false);
  assert.equal(parentUiState.result.base_rules.blocks.length, 1);
  const acceptedAdminEdit = await new Promise((resolve) => {
    runtimeMessage({ type: "admin_apply", rules: rules(["admin.example"]) }, null, resolve);
  });
  assert.equal(acceptedAdminEdit.ok, true);
  assert.equal(adminRequestCount, 1);
  assert.ok(scheduledTimeouts.includes(205_000));
  assert.equal(dynamicRules.length, 1);
  assert.equal(dynamicRules[0].condition.requestDomains.join(","), "admin.example");

  const liveManaged = await signedManaged(
    rules(["example.com", "school.example"]),
    keyPair,
    publicKeySpki,
  );
  for (const listener of nativePort.onMessage.listeners) {
    listener({ event: "snapshot", managed: liveManaged });
  }
  await new Promise((resolve) => setTimeout(resolve, 30));
  assert.equal(dynamicRules.length, 2);
  assert.equal(dynamicRules[1].condition.requestDomains.join(","), "school.example");

  // The minute alarm may only re-evaluate schedules in the newest verified
  // live snapshot. Firefox managed storage can remain one revision behind
  // until restart and must not overwrite live rules here.
  for (const listener of api.alarms.onAlarm.listeners) {
    listener({ name: "refresh-managed-rules" });
  }
  await new Promise((resolve) => setTimeout(resolve, 30));
  assert.equal(dynamicRules.length, 2);
  assert.equal(dynamicRules[1].condition.requestDomains.join(","), "school.example");

  const forgedManaged = await signedManaged(
    rules(["attacker.example"]),
    await cryptoModule.webcrypto.subtle.generateKey(
      { name: "ECDSA", namedCurve: "P-256" },
      true,
      ["sign", "verify"],
    ),
    publicKeySpki,
  );
  for (const listener of nativePort.onMessage.listeners) {
    listener({ event: "snapshot", managed: forgedManaged });
  }
  await new Promise((resolve) => setTimeout(resolve, 30));
  assert.equal(dynamicRules.length, 1);
  assert.equal(dynamicRules[0].condition.requestDomains.join(","), "example.com");
  console.log("Native Live-Regelupdate erfolgreich getestet.");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
