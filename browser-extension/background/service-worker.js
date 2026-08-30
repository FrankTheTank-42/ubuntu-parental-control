"use strict";

// Chrome loads only this MV3 service worker and therefore needs importScripts.
// Firefox loads the shared engine first through background.scripts; its
// background event-page context does not provide importScripts.
if (typeof globalThis.UPC_RULE_ENGINE === "undefined") {
  if (typeof globalThis.importScripts !== "function") {
    throw new Error("Ubuntu Parental Control: gemeinsame Regelengine fehlt");
  }
  globalThis.importScripts("../common/rule-engine.js");
}

const api = globalThis.browser ?? globalThis.chrome;
const isFirefox = typeof globalThis.browser !== "undefined";
const FAILSAFE_RULESET = "failsafe";
const FAILSAFE_RULE_ID = 1;
const REFRESH_ALARM = "refresh-managed-rules";
const NATIVE_HOST = "ubuntu_parental_control";
const NATIVE_REQUEST_TIMEOUT_MS = 10_000;
const ADMIN_REQUEST_TIMEOUT_MS = 205_000;
const CONTEXT_MENU_ROOT = "upc-add-current-domain";
const CONTEXT_MENU_PREFIX = `${CONTEXT_MENU_ROOT}:`;
const CONTEXT_MENU_OPEN_OPTIONS = "upc-open-rule-management";
const ACTION_MENU_ADD_ROOT = "upc-action-add-current-domain";
const ACTION_MENU_ADD_PREFIX = `${ACTION_MENU_ADD_ROOT}:`;
let updateChain = Promise.resolve();
let contextMenuChain = Promise.resolve();
let activeSnapshot = null;
let activeSnapshotSource = null;
let trustedLivePublicKey = null;
let nativePort = null;
let nativeConnected = false;
let nativeError = null;
let verifiedNativeStatus = null;
let reconnectTimer = null;
let requestCounter = 0;
const nativeRequests = new Map();

function rebuildContextMenus(rules) {
  contextMenuChain = contextMenuChain
    .catch(() => undefined)
    .then(async () => {
      await api.contextMenus.removeAll();
      api.contextMenus.create({
        id: CONTEXT_MENU_OPEN_OPTIONS,
        title: "Regelverwaltung öffnen",
        contexts: ["action"],
      });
      const blocking = rules.blocks.filter((block) => block.action === "block");
      if (!blocking.length) return;
      api.contextMenus.create({
        id: CONTEXT_MENU_ROOT,
        title: "Aktuelle Website zusätzlich blockieren",
        contexts: ["page"],
        documentUrlPatterns: ["http://*/*", "https://*/*"],
      });
      api.contextMenus.create({
        id: ACTION_MENU_ADD_ROOT,
        title: "Webseite zu Block hinzufügen",
        contexts: ["action"],
      });
      for (const block of blocking) {
        const commonChildProperties = {
          title: block.enabled ? block.name : `${block.name} (inaktiv)`,
          ...(isFirefox ? {
            icons: {
              "16": "icons/icon-16.png",
              "32": "icons/icon-32.png",
            },
          } : {}),
        };
        api.contextMenus.create({
          ...commonChildProperties,
          id: `${CONTEXT_MENU_PREFIX}${block.id}`,
          parentId: CONTEXT_MENU_ROOT,
          contexts: ["page"],
          documentUrlPatterns: ["http://*/*", "https://*/*"],
        });
        api.contextMenus.create({
          ...commonChildProperties,
          id: `${ACTION_MENU_ADD_PREFIX}${block.id}`,
          parentId: ACTION_MENU_ADD_ROOT,
          contexts: ["action"],
        });
      }
    })
    .catch((error) => {
      console.error("Ubuntu Parental Control: Kontextmenü konnte nicht aufgebaut werden", error);
    });
}

async function reloadDomainTabs(domain) {
  let tabs;
  try {
    tabs = await api.tabs.query({
      url: [`*://${domain}/*`, `*://*.${domain}/*`],
    });
  } catch (error) {
    console.warn(
      `Ubuntu Parental Control: offene Tabs für ${domain} konnten nicht ermittelt werden`,
      error,
    );
    return 0;
  }
  const tabIds = [...new Set(
    tabs.map((tab) => tab.id).filter((tabId) => Number.isInteger(tabId)),
  )];
  const results = await Promise.allSettled(
    tabIds.map((tabId) => api.tabs.reload(tabId, { bypassCache: true })),
  );
  for (const result of results) {
    if (result.status === "rejected") {
      console.warn("Ubuntu Parental Control: Tab konnte nicht neu geladen werden", result.reason);
    }
  }
  return results.filter((result) => result.status === "fulfilled").length;
}

async function openContextDomainAddition(info, tab) {
  if (typeof info?.menuItemId !== "string") return;
  let blockId;
  let sourceUrl;
  if (info.menuItemId.startsWith(CONTEXT_MENU_PREFIX)) {
    blockId = info.menuItemId.slice(CONTEXT_MENU_PREFIX.length);
    sourceUrl = info.pageUrl;
  } else if (info.menuItemId.startsWith(ACTION_MENU_ADD_PREFIX)) {
    blockId = info.menuItemId.slice(ACTION_MENU_ADD_PREFIX.length);
    sourceUrl = tab?.url;
  } else {
    return;
  }
  let page;
  try {
    page = new URL(sourceUrl);
  } catch (_error) {
    return;
  }
  if (!(["http:", "https:"].includes(page.protocol)) || !page.hostname) return;
  const optionsUrl = new URL(api.runtime.getURL("options/options.html"));
  optionsUrl.searchParams.set("context_block", blockId);
  optionsUrl.searchParams.set("context_domain", page.hostname.toLowerCase());
  await api.tabs.create({ url: optionsUrl.href });
}

function enqueueUpdate(reason) {
  updateChain = updateChain
    .catch(() => undefined)
    .then(() => refreshRules(reason))
    .catch(async (error) => {
      console.error("Ubuntu Parental Control: Regelaktivierung fehlgeschlagen", error);
      await activateFailSafe();
    });
  return updateChain;
}

async function setFailSafeEnabled(enabled) {
  await api.declarativeNetRequest.updateStaticRules({
    rulesetId: FAILSAFE_RULESET,
    enableRuleIds: enabled ? [FAILSAFE_RULE_ID] : [],
    disableRuleIds: enabled ? [] : [FAILSAFE_RULE_ID],
  });
}

async function activateFailSafe() {
  // The packaged static block is enabled before dynamic allow rules are
  // removed. This ordering never creates an unintended open interval.
  await setFailSafeEnabled(true);
  const existing = await api.declarativeNetRequest.getDynamicRules();
  if (existing.length) {
    await api.declarativeNetRequest.updateDynamicRules({
      removeRuleIds: existing.map((rule) => rule.id),
      addRules: [],
    });
  }
}

async function verifyRegexRules(rules) {
  for (const rule of rules) {
    const pattern = rule.condition.regexFilter;
    if (!pattern) continue;
    const result = await api.declarativeNetRequest.isRegexSupported({
      regex: pattern,
      isCaseSensitive: rule.condition.isUrlFilterCaseSensitive === true,
    });
    if (!result.isSupported) {
      throw new Error(`Regex wird vom Browser nicht unterstützt: ${result.reason ?? pattern}`);
    }
  }
}

async function installRules(compiled) {
  await verifyRegexRules(compiled.rules);
  const dynamicLimit = api.declarativeNetRequest.MAX_NUMBER_OF_DYNAMIC_RULES;
  if (Number.isInteger(dynamicLimit) && compiled.rules.length > dynamicLimit) {
    throw new Error(`DNR-Regelgrenze überschritten: ${compiled.rules.length}/${dynamicLimit}`);
  }

  const existing = await api.declarativeNetRequest.getDynamicRules();
  // updateDynamicRules is atomic: invalid additions leave the old set intact.
  await api.declarativeNetRequest.updateDynamicRules({
    removeRuleIds: existing.map((rule) => rule.id),
    addRules: compiled.rules,
  });
  await setFailSafeEnabled(compiled.defaultAction === "block");
}

async function activateManagedData(managed, reason, source = "managed") {
  if (source === "native") {
    await UPC_RULE_ENGINE.verifyLiveSnapshot(managed, trustedLivePublicKey);
  }
  const snapshot = await UPC_RULE_ENGINE.parseManagedSnapshot(managed);
  if (source === "managed" && managed.live_public_key_spki !== undefined) {
    trustedLivePublicKey = await UPC_RULE_ENGINE.validateLivePublicKey(
      managed.live_public_key_spki,
    );
  }
  if (activeSnapshot?.revision === snapshot.revision) {
    // A native write is intentionally returned both as the direct command
    // response and as a live file event. Treat the second delivery as an
    // acknowledgement instead of trying to register identical DNR rule IDs
    // again. A native confirmation upgrades a managed startup snapshot to the
    // live source without changing its already installed rules.
    if (source === "native") activeSnapshotSource = "native";
    console.info(
      `Ubuntu Parental Control: Revision ${snapshot.revision.slice(0, 12)} bereits aktiv ` +
        `(Grund ${reason})`,
    );
    return activeSnapshot;
  }
  const compiled = UPC_RULE_ENGINE.compile(snapshot.rules, new Date());
  await installRules(compiled);
  activeSnapshot = snapshot;
  activeSnapshotSource = source;
  rebuildContextMenus(snapshot.rules);
  console.info(
    `Ubuntu Parental Control: ${compiled.rules.length} Regeln aktiviert ` +
      `(Revision ${snapshot.revision.slice(0, 12)}, Grund ${reason})`,
  );
  return snapshot;
}

function enqueueNativeActivation(managed, reason) {
  const activation = updateChain
    .catch(() => undefined)
    .then(() => activateManagedData(managed, reason, "native"));
  updateChain = activation;
  return activation;
}

async function recompileActiveSnapshot(reason) {
  if (activeSnapshot === null) return refreshRules(reason);
  const compiled = UPC_RULE_ENGINE.compile(activeSnapshot.rules, new Date());
  await installRules(compiled);
  console.info(
    `Ubuntu Parental Control: ${compiled.rules.length} Regeln neu ausgewertet ` +
      `(Revision ${activeSnapshot.revision.slice(0, 12)}, Grund ${reason})`,
  );
  return activeSnapshot;
}

function enqueueScheduleRecompile(reason) {
  updateChain = updateChain
    .catch(() => undefined)
    .then(() => recompileActiveSnapshot(reason))
    .catch(async (error) => {
      console.error("Ubuntu Parental Control: Zeitplan-Auswertung fehlgeschlagen", error);
      await activateFailSafe();
    });
  return updateChain;
}

async function refreshRules(reason) {
  if (reason === "managed-policy-change" && activeSnapshotSource === "native") {
    console.info(
      "Ubuntu Parental Control: verspätete Managed-Policy-Änderung ignoriert; " +
        "verifizierter Native Snapshot bleibt aktiv",
    );
    return activeSnapshot;
  }
  const managed = await api.storage.managed.get([
    "protocol_version",
    "revision",
    "snapshot_json",
    "live_public_key_spki",
  ]);
  // The managed-storage read can complete after a native activation that was
  // queued later. Re-check the source here to prevent that older read from
  // replacing the live snapshot.
  if (reason === "managed-policy-change" && activeSnapshotSource === "native") {
    console.info(
      "Ubuntu Parental Control: veralteten Managed-Policy-Stand nach Native-Aktivierung verworfen",
    );
    return activeSnapshot;
  }
  return activateManagedData(managed, reason);
}

function rejectNativeRequests(message) {
  for (const { reject, timer } of nativeRequests.values()) {
    clearTimeout(timer);
    reject(new Error(message));
  }
  nativeRequests.clear();
}

function scheduleNativeReconnect() {
  if (reconnectTimer !== null) return;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connectNativeHost();
  }, 5000);
}

function connectNativeHost() {
  if (nativePort !== null) return;
  try {
    const port = api.runtime.connectNative(NATIVE_HOST);
    nativePort = port;
    port.onMessage.addListener(handleNativeMessage);
    port.onDisconnect.addListener(() => {
      const message = api.runtime.lastError?.message ?? "Native Host wurde getrennt";
      nativeConnected = false;
      nativeError = message;
      verifiedNativeStatus = null;
      nativePort = null;
      rejectNativeRequests(message);
      scheduleNativeReconnect();
    });
  } catch (error) {
    nativeConnected = false;
    nativeError = error.message;
    nativePort = null;
    scheduleNativeReconnect();
  }
}

function handleNativeMessage(message) {
  if (!message || typeof message !== "object") return;
  if (message.event === "native_status") {
    nativeConnected = message.connected === true;
    if (!nativeConnected) verifiedNativeStatus = null;
    nativeError = null;
    return;
  }
  if (message.event === "native_error") {
    nativeError = String(message.error ?? "Unbekannter Native-Host-Fehler");
    return;
  }
  if (message.event === "snapshot") {
    updateChain = updateChain
      .catch(() => undefined)
      .then(() => activateManagedData(message.managed, "native-live-update", "native"))
      .catch((error) => {
        console.error("Ubuntu Parental Control: Native Snapshot abgelehnt", error);
        return refreshRules("native-snapshot-fallback");
      })
      .catch(async (error) => {
        console.error("Ubuntu Parental Control: auch Managed-Fallback fehlgeschlagen", error);
        await activateFailSafe();
      });
    return;
  }
  if (message.id && nativeRequests.has(message.id)) {
    const pending = nativeRequests.get(message.id);
    nativeRequests.delete(message.id);
    clearTimeout(pending.timer);
    if (message.ok) pending.resolve(message.result);
    else pending.reject(new Error(String(message.error ?? "Native Anfrage abgelehnt")));
  }
}

function requestNative(command, timeoutMs = NATIVE_REQUEST_TIMEOUT_MS) {
  connectNativeHost();
  if (nativePort === null) return Promise.reject(new Error(nativeError ?? "Native Host nicht verfügbar"));
  const id = `${Date.now()}-${++requestCounter}`;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      nativeRequests.delete(id);
      reject(new Error(`Zeitüberschreitung beim Native Host (${command.command})`));
    }, timeoutMs);
    nativeRequests.set(id, { resolve, reject, timer });
    try {
      nativePort.postMessage({ id, ...command });
    } catch (error) {
      clearTimeout(timer);
      nativeRequests.delete(id);
      reject(error);
    }
  });
}

function makeNonce() {
  const bytes = new Uint8Array(24);
  crypto.getRandomValues(bytes);
  return [...bytes].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function verifyNativeStatus(signedStatus, expectedNonce) {
  if (!signedStatus || typeof signedStatus !== "object") {
    throw new Error("Native Berechtigungsstatus fehlt");
  }
  await UPC_RULE_ENGINE.verifySignedText(
    signedStatus.authorization_json,
    signedStatus.authorization_signature,
    trustedLivePublicKey,
    "Berechtigungssignatur",
  );
  let status;
  try {
    status = JSON.parse(signedStatus.authorization_json);
  } catch (error) {
    throw new Error(`Berechtigungsstatus ist kein JSON: ${error.message}`);
  }
  if (
    status?.protocol_version !== 1 ||
    status.nonce !== expectedNonce ||
    !Number.isInteger(status.uid) ||
    typeof status.restricted !== "boolean" ||
    !Array.isArray(status.can_add_domains_to)
  ) {
    throw new Error("Berechtigungsstatus ist ungültig oder gehört zu einer anderen Anfrage");
  }
  return status;
}

async function handleUiMessage(message) {
  if (!message || typeof message !== "object") throw new Error("Ungültige Anfrage");
  if (message.type === "get_ui_state") {
    let nativeStatus = null;
    let baseRules = null;
    let userDomains = null;
    if (activeSnapshot === null) {
      try {
        await enqueueUpdate("options-page-open");
      } catch (_error) {
        // The state below reports the missing snapshot without weakening the
        // already active fail-safe behavior.
      }
    }
    verifiedNativeStatus = null;
    try {
      const nonce = makeNonce();
      const signedStatus = await requestNative({ command: "status", nonce });
      nativeStatus = await verifyNativeStatus(signedStatus, nonce);
      verifiedNativeStatus = nativeStatus;
      if (!nativeStatus.restricted) {
        const adminState = await requestNative({ command: "base_rules" });
        baseRules = adminState.rules;
        userDomains = adminState.user_domains;
      } else {
        const childState = await requestNative({ command: "own_user_domains" });
        userDomains = childState.user_domains;
      }
    } catch (error) {
      nativeError = error.message;
    }
    return {
      revision: activeSnapshot?.revision ?? null,
      rules: activeSnapshot?.rules ?? null,
      base_rules: baseRules,
      user_domains: userDomains,
      native: {
        connected: nativeConnected,
        error: nativeError,
        status: nativeStatus,
      },
    };
  }
  if (message.type === "add_domain") {
    const result = await requestNative({
      command: "add_domain",
      block_id: message.block_id,
      domain: message.domain,
    });
    if (!result.managed) {
      throw new Error("Native Host hat keinen bestätigten Regelsnapshot zurückgegeben");
    }
    const snapshot = await enqueueNativeActivation(result.managed, "user-domain-added");
    const block = snapshot.rules.blocks.find((item) => item.id === message.block_id);
    if (!block?.targets.domains.includes(message.domain)) {
      throw new Error("Domain fehlt im bestätigten Regelsnapshot");
    }
    return {
      ...result,
      reloaded_tabs: await reloadDomainTabs(message.domain),
    };
  }
  if (message.type === "admin_apply") {
    if (!verifiedNativeStatus || verifiedNativeStatus.restricted) {
      throw new Error("Administrative Bearbeitung ist in diesem Konto nicht freigeschaltet");
    }
    const result = await requestNative(
      { command: "admin_apply", rules: message.rules },
      ADMIN_REQUEST_TIMEOUT_MS,
    );
    if (result.managed) {
      await enqueueNativeActivation(result.managed, "administrator-rules-applied");
    }
    return result;
  }
  if (message.type === "admin_remove_user_domain") {
    if (!verifiedNativeStatus || verifiedNativeStatus.restricted) {
      throw new Error("Administrative Bearbeitung ist in diesem Konto nicht freigeschaltet");
    }
    const result = await requestNative(
      {
        command: "admin_remove_user_domain",
        uid: message.uid,
        block_id: message.block_id,
        domain: message.domain,
      },
      ADMIN_REQUEST_TIMEOUT_MS,
    );
    if (result.managed) {
      await enqueueNativeActivation(result.managed, "administrator-user-domain-removed");
    }
    return result;
  }
  throw new Error("Unbekannte Anfrage");
}

api.runtime.onInstalled.addListener(() => enqueueUpdate("installation"));
api.runtime.onStartup.addListener(() => enqueueUpdate("browser-start"));
api.storage.onChanged.addListener((_changes, areaName) => {
  if (areaName === "managed") enqueueUpdate("managed-policy-change");
});
api.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === REFRESH_ALARM) enqueueScheduleRecompile("schedule-tick");
});
api.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  handleUiMessage(message).then(
    (result) => sendResponse({ ok: true, result }),
    (error) => sendResponse({ ok: false, error: error.message }),
  );
  return true;
});
api.contextMenus.onClicked.addListener((info, tab) => {
  const action = info.menuItemId === CONTEXT_MENU_OPEN_OPTIONS
    ? api.runtime.openOptionsPage()
    : openContextDomainAddition(info, tab);
  action.catch((error) => {
    console.error("Ubuntu Parental Control: Kontextmenü-Aktion fehlgeschlagen", error);
  });
});
api.action.onClicked.addListener(() => {
  api.runtime.openOptionsPage().catch((error) => {
    console.error("Ubuntu Parental Control: Regelverwaltung konnte nicht geöffnet werden", error);
  });
});

api.alarms.create(REFRESH_ALARM, { periodInMinutes: 1 });
enqueueUpdate("service-worker-start");
