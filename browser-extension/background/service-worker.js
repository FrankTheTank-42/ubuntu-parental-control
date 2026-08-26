"use strict";

importScripts("../common/rule-engine.js");

const api = globalThis.browser ?? globalThis.chrome;
const FAILSAFE_RULESET = "failsafe";
const FAILSAFE_RULE_ID = 1;
const REFRESH_ALARM = "refresh-managed-rules";
let updateChain = Promise.resolve();

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

async function refreshRules(reason) {
  const managed = await api.storage.managed.get([
    "protocol_version",
    "revision",
    "snapshot_json",
  ]);
  const snapshot = await UPC_RULE_ENGINE.parseManagedSnapshot(managed);
  const compiled = UPC_RULE_ENGINE.compile(snapshot.rules, new Date());
  await installRules(compiled);
  console.info(
    `Ubuntu Parental Control: ${compiled.rules.length} Regeln aktiviert ` +
      `(Revision ${snapshot.revision.slice(0, 12)}, Grund ${reason})`,
  );
}

api.runtime.onInstalled.addListener(() => enqueueUpdate("installation"));
api.runtime.onStartup.addListener(() => enqueueUpdate("browser-start"));
api.storage.onChanged.addListener((_changes, areaName) => {
  if (areaName === "managed") enqueueUpdate("managed-policy-change");
});
api.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === REFRESH_ALARM) enqueueUpdate("schedule-tick");
});

api.alarms.create(REFRESH_ALARM, { periodInMinutes: 1 });
enqueueUpdate("service-worker-start");
