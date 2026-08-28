"use strict";

const api = globalThis.browser ?? globalThis.chrome;
const isFirefox = typeof globalThis.browser !== "undefined";
const blocksElement = document.querySelector("#blocks");
const template = document.querySelector("#block-template");
const messageElement = document.querySelector("#message");
let currentState = null;
let adminBusy = false;
let refreshAfterRepair = false;
let pendingContextAddition = (() => {
  const parameters = new URLSearchParams(location.search);
  const blockId = parameters.get("context_block");
  const domain = parameters.get("context_domain");
  if (!blockId || !domain) return null;
  history.replaceState(null, "", location.pathname);
  return { blockId, domain: domain.toLowerCase() };
})();

async function send(message) {
  const response = await api.runtime.sendMessage(message);
  if (!response?.ok) throw new Error(response?.error ?? "Unbekannter Erweiterungsfehler");
  return response.result;
}

function showMessage(text, error = false) {
  messageElement.textContent = text;
  messageElement.classList.toggle("error", error);
  messageElement.hidden = false;
}

function clearStaleError() {
  if (!messageElement.classList.contains("error")) return;
  messageElement.hidden = true;
  messageElement.textContent = "";
  messageElement.classList.remove("error");
}

function badge(text, className = "") {
  const item = document.createElement("span");
  item.className = `badge ${className}`.trim();
  item.textContent = text;
  return item;
}

function nativeFailure(native) {
  const error = String(native?.error ?? "").trim();
  if (!native?.connected) {
    let reason = "Der Browser konnte den lokalen Native Host nicht starten oder keine Verbindung zu ihm herstellen.";
    if (/no such native application|native.*host.*not found|nicht gefunden/i.test(error)) {
      reason = "Der Browser hat die Registrierung des lokalen Native Hosts nicht gefunden.";
    } else if (/permission|denied|not allowed|verweigert|berechtigung/i.test(error)) {
      reason = "Der Browser oder das WebExtensions-Portal hat den Zugriff auf den Native Host verweigert.";
      if (isFirefox) {
        reason +=
          " Starte im betroffenen Ubuntu-Konto „Ubuntu Parental Control – Firefox verbinden“, "
          + "um die lokale Verbindung wieder zu erlauben.";
      }
    } else if (/timeout|zeitüberschreitung/i.test(error)) {
      reason = "Der Native Host hat nicht rechtzeitig geantwortet.";
    } else if (/disconnect|closed|exit|getrennt|beendet/i.test(error)) {
      reason = "Der Native Host wurde nach dem Start unerwartet beendet oder getrennt.";
    }
    return {
      title: "Native Host nicht erreichbar",
      detail: `${reason} Die aktiven Filterregeln bleiben erhalten, Änderungen sind jedoch gesperrt.`,
      technical: error,
    };
  }
  return {
    title: "Kontoberechtigung nicht bestätigt",
    detail: "Der Native Host ist verbunden, aber die sichere Zuordnung zum Eltern- oder Kinderkonto ist fehlgeschlagen. Änderungen sind deshalb gesperrt.",
    technical: error,
  };
}

function renderConnection(native) {
  const connection = document.querySelector("#connection");
  const title = document.querySelector("#connection-title");
  const detail = document.querySelector("#connection-detail");
  const errorDetail = document.querySelector("#connection-error-detail");
  const repair = document.querySelector("#repair-native");
  connection.classList.remove("connected", "error");
  errorDetail.hidden = true;
  errorDetail.textContent = "";
  repair.hidden = true;
  if (!native.connected || !native.status) {
    const failure = nativeFailure(native);
    connection.classList.add("error");
    title.textContent = failure.title;
    detail.textContent = failure.detail;
    if (failure.technical) {
      errorDetail.textContent = `Technisches Detail: ${failure.technical}`;
      errorDetail.hidden = false;
    }
    document.querySelector("#view-mode").textContent = "Nur-Lesen-Ansicht";
    if (!native.connected && isFirefox) repair.hidden = false;
    return;
  }
  connection.classList.add("connected");
  if (native.status.restricted) {
    title.textContent = "Eingeschränktes Konto verbunden";
    detail.textContent = "Du kannst jede Blockierliste um Domains ergänzen. Löschen und Lockern ist nicht möglich.";
    document.querySelector("#view-mode").textContent = "Kinderansicht";
  } else {
    title.textContent = "Administrativer Editor verfügbar";
    detail.textContent = "Änderungen benötigen bei jedem Speichern eine Polkit-Administratoranmeldung.";
    document.querySelector("#view-mode").textContent = "Elternansicht";
  }
}

function scheduleText(block) {
  if (!block.schedule) return "durchgehend aktiv";
  const count = block.schedule.windows.length;
  return `${count} Zeitfenster · ${block.schedule.timezone}`;
}

function lines(value) {
  return value.split("\n").map((item) => item.trim()).filter(Boolean);
}

function regexLines(items) {
  return items.map((item) => `${item.case_sensitive ? "s" : "i"}:${item.pattern}`).join("\n");
}

function parseRegexLines(value) {
  return lines(value).map((line) => {
    const match = /^(i|s):(.*)$/.exec(line);
    if (!match || !match[2]) throw new Error(`Regex benötigt Präfix i: oder s:: ${line}`);
    return { pattern: match[2], case_sensitive: match[1] === "s" };
  });
}

function blockIdFromName(name, blocks) {
  let base = name
    .toLocaleLowerCase("de-DE")
    .replaceAll("ß", "ss")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  if (!/^[a-z]/.test(base)) base = `block-${base || "neu"}`;
  base = base.slice(0, 64).replace(/-+$/g, "");
  const existing = new Set(blocks.map((block) => block.id));
  if (!existing.has(base)) return base;
  for (let number = 2; number < 10_000; number += 1) {
    const suffix = `-${number}`;
    const candidate = `${base.slice(0, 64 - suffix.length).replace(/-+$/g, "")}${suffix}`;
    if (!existing.has(candidate)) return candidate;
  }
  throw new Error("Für diesen Blocknamen konnte keine eindeutige technische ID erzeugt werden.");
}

function normalizedBlockName(name) {
  return name.normalize("NFKC").trim().toLocaleLowerCase("de-DE").replaceAll("ß", "ss");
}

function userDomainOwner(state, blockId, domain) {
  const users = state.user_domains?.users ?? {};
  for (const [uid, blocks] of Object.entries(users)) {
    if (blocks[blockId]?.includes(domain)) return Number(uid);
  }
  return null;
}

function setAdminBusy(busy) {
  adminBusy = busy;
  document.body.classList.toggle("saving", busy);
  document.body.setAttribute("aria-busy", String(busy));
  document.querySelector("#busy-overlay").hidden = !busy;
  for (const button of document.querySelectorAll(
    ".admin-form button, #create-block, .remove-user-domain",
  )) {
    button.disabled = busy || button.dataset.permanentlyDisabled === "true";
  }
}

async function runAdminOperation(operation, successMessage) {
  if (adminBusy) throw new Error("Eine Administrator-Anfrage läuft bereits.");
  setAdminBusy(true);
  showMessage("Administrator-Anmeldung wird geöffnet – bitte den Dialog einmal bestätigen …");
  try {
    await operation();
    showMessage(successMessage);
    await new Promise((resolve) => setTimeout(resolve, 1300));
    await load();
  } finally {
    setAdminBusy(false);
  }
}

async function applyAdminRules(rules, successMessage) {
  await runAdminOperation(
    () => send({ type: "admin_apply", rules }),
    successMessage,
  );
}

async function applyContextDomain(state, addition) {
  const block = state.rules?.blocks.find((item) => item.id === addition.blockId);
  if (!block || block.action !== "block") {
    throw new Error("Die ausgewählte Blockierliste ist nicht mehr verfügbar.");
  }
  if (block.targets.domains.includes(addition.domain)) {
    throw new Error(`${addition.domain} ist bereits in „${block.name}“ enthalten.`);
  }
  if (!state.native.connected || !state.native.status) {
    throw new Error(nativeFailure(state.native).detail);
  }
  if (state.native.status.restricted) {
    setAdminBusy(true);
    showMessage(`${addition.domain} wird zu „${block.name}“ hinzugefügt …`);
    try {
      await send({
        type: "add_domain",
        block_id: block.id,
        domain: addition.domain,
      });
      showMessage(
        `${addition.domain} wurde als geschützte Kinderergänzung zu „${block.name}“ gespeichert.`,
      );
      await load();
    } finally {
      setAdminBusy(false);
    }
    return;
  }
  if (!state.base_rules) {
    throw new Error("Die administrativen Basisregeln sind nicht verfügbar.");
  }
  const rules = structuredClone(state.base_rules);
  const baseBlock = rules.blocks.find((item) => item.id === block.id);
  if (!baseBlock || baseBlock.action !== "block") {
    throw new Error("Die ausgewählte Blockierliste ist administrativ nicht verfügbar.");
  }
  baseBlock.targets.domains.push(addition.domain);
  baseBlock.targets.domains.sort();
  await applyAdminRules(
    rules,
    `${addition.domain} wurde dauerhaft zu „${baseBlock.name}“ hinzugefügt.`,
  );
}

function setupAdminForm(card, block, baseRules, editable) {
  const form = card.querySelector(".admin-form");
  form.hidden = false;
  form.querySelector(".admin-name").value = block.name;
  form.querySelector(".admin-enabled").checked = block.enabled;
  form.querySelector(".admin-action").value = block.action;
  form.querySelector(".admin-priority").value = String(block.priority);
  form.querySelector(".admin-domains").value = block.targets.domains.join("\n");
  form.querySelector(".admin-patterns").value = block.targets.url_patterns.join("\n");
  form.querySelector(".admin-regex").value = regexLines(block.targets.url_regex);
  form.querySelector(".admin-exceptions").value = block.exceptions.domains.join("\n");
  form.querySelector(".admin-schedule").value = block.schedule
    ? JSON.stringify(block.schedule, null, 2)
    : "";
  if (!editable) {
    form.classList.add("locked");
    form.querySelector(".admin-title strong").textContent = "Nur für Eltern bearbeitbar";
    form.querySelector(".admin-title span").textContent =
      "Du kannst diese Einstellungen ansehen, aber nicht ändern.";
    for (const control of form.querySelectorAll("input, select, textarea, button")) {
      control.disabled = true;
      if (control instanceof HTMLButtonElement) {
        control.dataset.permanentlyDisabled = "true";
      }
    }
    return;
  }
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const rules = structuredClone(baseRules);
    const edited = rules.blocks.find((item) => item.id === block.id);
    try {
      const newName = form.querySelector(".admin-name").value.trim();
      const duplicate = rules.blocks.find(
        (item) => item.id !== block.id
          && normalizedBlockName(item.name) === normalizedBlockName(newName),
      );
      if (duplicate) {
        throw new Error(
          `Der Name „${duplicate.name}“ wird bereits von Block ${duplicate.id} verwendet.`,
        );
      }
      edited.name = newName;
      edited.enabled = form.querySelector(".admin-enabled").checked;
      edited.action = form.querySelector(".admin-action").value;
      edited.user_permissions.add_domains = edited.action === "block";
      edited.priority = Number(form.querySelector(".admin-priority").value);
      edited.targets.domains = lines(form.querySelector(".admin-domains").value);
      edited.targets.url_patterns = lines(form.querySelector(".admin-patterns").value);
      edited.targets.url_regex = parseRegexLines(form.querySelector(".admin-regex").value);
      edited.exceptions.domains = lines(form.querySelector(".admin-exceptions").value);
      const schedule = form.querySelector(".admin-schedule").value.trim();
      if (schedule) edited.schedule = JSON.parse(schedule);
      else delete edited.schedule;
      await applyAdminRules(rules, `„${edited.name}“ wurde gespeichert.`);
    } catch (error) {
      showMessage(error.message, true);
    }
  });
  card.querySelector(".delete-block").addEventListener("click", async () => {
    if (!confirm(`Block „${block.name}“ wirklich löschen?`)) return;
    const rules = structuredClone(baseRules);
    rules.blocks = rules.blocks.filter((item) => item.id !== block.id);
    try {
      await applyAdminRules(rules, `„${block.name}“ wurde gelöscht.`);
    } catch (error) {
      showMessage(error.message, true);
    }
  });
}

function renderBlocks(state) {
  const adminMode = state.native.connected && state.native.status && !state.native.status.restricted;
  const childMode = state.native.connected && state.native.status?.restricted;
  document.body.classList.remove("mode-loading", "mode-parent", "mode-child", "mode-readonly");
  document.body.classList.add(adminMode ? "mode-parent" : childMode ? "mode-child" : "mode-readonly");
  const rules = state.rules;
  blocksElement.replaceChildren();
  if (!rules) {
    showMessage("Es ist noch kein gültiger Regelsnapshot verfügbar.", true);
    return;
  }
  let domainCount = 0;
  for (const block of rules.blocks) {
    const baseBlock = adminMode
      ? state.base_rules?.blocks.find((item) => item.id === block.id)
      : null;
    const ownDomains = new Set(
      state.user_domains?.users?.[String(state.native.status?.uid)]?.[block.id] ?? [],
    );
    const baseDomains = new Set(
      baseBlock?.targets.domains
        ?? block.targets.domains.filter((domain) => !ownDomains.has(domain)),
    );
    domainCount += block.targets.domains.length;
    const card = template.content.firstElementChild.cloneNode(true);
    card.querySelector(".block-name").textContent = block.name;
    card.querySelector(".block-id").textContent = `Technische ID: ${block.id}`;
    card.querySelector(".block-id").title =
      "Automatisch erzeugte interne Kennung. Sie besteht aus Kleinbuchstaben, Zahlen und Bindestrichen.";
    const badges = card.querySelector(".badges");
    badges.append(
      badge(block.action === "block" ? "Blockieren" : "Erlauben", block.action),
      badge(block.enabled ? "Aktiv" : "Inaktiv", block.enabled ? "" : "inactive"),
      badge(`Priorität ${block.priority}`),
    );
    card.querySelector(".block-meta").textContent = scheduleText(block);
    const domains = card.querySelector(".domain-list");
    if (block.targets.domains.length) {
      for (const domain of block.targets.domains) {
        const item = document.createElement("span");
        item.className = `domain ${baseDomains.has(domain) ? "" : "user-added"}`.trim();
        item.textContent = domain;
        if (!baseDomains.has(domain)) {
          const ownerUid = userDomainOwner(state, block.id, domain);
          item.title = childMode && ownerUid === state.native.status.uid
            ? "Von dir als geschützte Kinderergänzung gespeichert"
            : ownerUid
              ? `Von eingeschränktem Konto UID ${ownerUid} ergänzt`
              : "Von einem eingeschränkten Konto ergänzt";
          if (adminMode && ownerUid) {
            const remove = document.createElement("button");
            remove.type = "button";
            remove.className = "remove-user-domain";
            remove.textContent = "×";
            remove.title = "Benutzer-Ergänzung als Administrator entfernen";
            remove.addEventListener("click", async () => {
              if (!confirm(`${domain} aus den Ergänzungen von UID ${ownerUid} entfernen?`)) return;
              try {
                await runAdminOperation(
                  () => send({
                    type: "admin_remove_user_domain",
                    uid: ownerUid,
                    block_id: block.id,
                    domain,
                  }),
                  `${domain} wurde aus den Benutzer-Ergänzungen entfernt.`,
                );
              } catch (error) {
                showMessage(error.message, true);
              }
            });
            item.append(remove);
          }
        }
        domains.append(item);
      }
    } else {
      const empty = document.createElement("span");
      empty.className = "empty";
      empty.textContent = "Keine Domain-Ziele";
      domains.append(empty);
    }

    const form = card.querySelector(".add-domain-form");
    if (childMode && block.action === "block") {
      form.hidden = false;
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (adminBusy) return;
        const input = form.querySelector(".domain-input");
        const button = form.querySelector("button");
        const domain = input.value.trim().toLowerCase();
        setAdminBusy(true);
        button.disabled = true;
        showMessage(`${domain} wird gespeichert …`);
        try {
          await send({ type: "add_domain", block_id: block.id, domain });
          input.value = "";
          showMessage(
            `${domain} wurde als geschützte Kinderergänzung zu „${block.name}“ gespeichert.`,
          );
          await load();
        } catch (error) {
          showMessage(error.message, true);
        } finally {
          button.disabled = false;
          setAdminBusy(false);
        }
      });
    } else if (
      block.action === "block"
      && (!state.native.connected || !state.native.status || childMode)
    ) {
      const unavailable = card.querySelector(".add-domain-unavailable");
      unavailable.hidden = false;
      const unavailableDetail = unavailable.querySelector(".add-domain-unavailable-detail");
      if (!state.native.connected || !state.native.status) {
        unavailableDetail.textContent = nativeFailure(state.native).detail;
      } else {
        unavailableDetail.textContent =
          "Der Native Host hat für diese Blockierliste keine sichere Schreibfreigabe zurückgegeben.";
      }
    }
    if (adminMode && state.base_rules && baseBlock) {
      setupAdminForm(card, baseBlock, state.base_rules, true);
    } else if (childMode) {
      setupAdminForm(card, block, null, false);
    }
    blocksElement.append(card);
  }
  document.querySelector("#block-count").textContent = String(rules.blocks.length);
  document.querySelector("#domain-count").textContent = String(domainCount);
  document.querySelector("#revision").textContent = state.revision?.slice(0, 10) ?? "–";
  document.querySelector("#default-action").textContent =
    `Standard: ${rules.profile.default_action === "block" ? "blockieren" : "erlauben"}`;
  const createButton = document.querySelector("#create-block");
  createButton.hidden = !(adminMode || childMode);
  createButton.disabled = childMode;
  createButton.dataset.permanentlyDisabled = childMode ? "true" : "false";
  createButton.title = childMode ? "Nur ein Elternkonto kann neue Blocks anlegen." : "";
}

async function load() {
  try {
    const state = await send({ type: "get_ui_state" });
    clearStaleError();
    currentState = state;
    renderConnection(state.native);
    renderBlocks(state);
    if (pendingContextAddition) {
      const addition = pendingContextAddition;
      pendingContextAddition = null;
      try {
        await applyContextDomain(state, addition);
      } catch (error) {
        showMessage(`Website konnte nicht hinzugefügt werden: ${error.message}`, true);
      }
    }
  } catch (error) {
    renderConnection({ connected: false, error: error.message, status: null });
    showMessage(error.message, true);
  }
}

document.querySelector("#refresh").addEventListener("click", load);
document.querySelector("#repair-native").addEventListener("click", () => {
  refreshAfterRepair = true;
  showMessage(
    "Das lokale Einwilligungswerkzeug wird geöffnet. Kehre danach zu dieser Seite zurück.",
  );
});
window.addEventListener("focus", () => {
  if (!refreshAfterRepair) return;
  refreshAfterRepair = false;
  setTimeout(load, 500);
});
document.querySelector("#create-block").addEventListener("click", async () => {
  if (!currentState?.base_rules) return;
  const name = prompt(
    "Wie soll der Block heißen?\n\n" +
    "Beispiel: Soziale Medien am Abend\n" +
    "Die benötigte technische ID wird automatisch daraus erzeugt.",
  )?.trim();
  if (!name) return;
  const duplicate = currentState.base_rules.blocks.find(
    (block) => normalizedBlockName(block.name) === normalizedBlockName(name),
  );
  if (duplicate) {
    showMessage(
      `Ein Block namens „${duplicate.name}“ existiert bereits ` +
        `(technische ID: ${duplicate.id}).`,
      true,
    );
    return;
  }
  const domain = prompt("Erste zu blockierende Domain:")?.trim().toLowerCase();
  if (!domain) return;
  const rules = structuredClone(currentState.base_rules);
  let id;
  try {
    id = blockIdFromName(name, rules.blocks);
  } catch (error) {
    showMessage(error.message, true);
    return;
  }
  rules.blocks.push({
    id,
    name,
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
    targets: { domains: [domain], url_patterns: [], url_regex: [] },
    exceptions: { domains: [], url_patterns: [], url_regex: [] },
    limits: null,
  });
  try {
    await applyAdminRules(rules, `„${name}“ wurde angelegt.`);
  } catch (error) {
    showMessage(error.message, true);
  }
});
load();
