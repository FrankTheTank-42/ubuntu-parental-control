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
const FAILSAFE_RULESET = "failsafe";
const FAILSAFE_RULE_ID = 1;
const REFRESH_ALARM = "refresh-managed-rules";
const NATIVE_HOST = "ubuntu_parental_control";
const NATIVE_REQUEST_TIMEOUT_MS = 10_000;
const ADMIN_REQUEST_TIMEOUT_MS = 205_000;
let updateChain = Promise.resolve();
let activeSnapshot = null;
let trustedLivePublicKey = null;
let nativePort = null;
let nativeConnected = false;
let nativeError = null;
let verifiedNativeStatus = null;
let reconnectTimer = null;
let requestCounter = 0;
const nativeRequests = new Map();

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
  const compiled = UPC_RULE_ENGINE.compile(snapshot.rules, new Date());
  await installRules(compiled);
  activeSnapshot = snapshot;
  console.info(
    `Ubuntu Parental Control: ${compiled.rules.length} Regeln aktiviert ` +
      `(Revision ${snapshot.revision.slice(0, 12)}, Grund ${reason})`,
  );
  return snapshot;
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
  const managed = await api.storage.managed.get([
    "protocol_version",
    "revision",
    "snapshot_json",
    "live_public_key_spki",
  ]);
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
    if (result.managed) {
      await activateManagedData(result.managed, "user-domain-added", "native");
    }
    return result;
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
      await activateManagedData(result.managed, "administrator-rules-applied", "native");
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
      await activateManagedData(result.managed, "administrator-user-domain-removed", "native");
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

api.alarms.create(REFRESH_ALARM, { periodInMinutes: 1 });
enqueueUpdate("service-worker-start");
connectNativeHost();
