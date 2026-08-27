"use strict";

const api = globalThis.browser ?? globalThis.chrome;
const blocksElement = document.querySelector("#blocks");
const template = document.querySelector("#block-template");
const messageElement = document.querySelector("#message");
let currentState = null;
let adminBusy = false;

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

function renderConnection(native) {
  const connection = document.querySelector("#connection");
  const title = document.querySelector("#connection-title");
  const detail = document.querySelector("#connection-detail");
  connection.classList.remove("connected", "error");
  if (!native.connected) {
    connection.classList.add("error");
    title.textContent = "Nur-Lesen-Modus";
    detail.textContent = native.error
      ? `Der sichere Verwaltungsdienst ist nicht erreichbar: ${native.error}`
      : "Der sichere Verwaltungsdienst ist nicht erreichbar.";
    document.querySelector("#view-mode").textContent = "Nur-Lesen-Ansicht";
    return;
  }
  if (!native.status) {
    connection.classList.add("error");
    title.textContent = "Nur-Lesen-Modus";
    detail.textContent = native.error
      ? `Der Kontostatus konnte nicht sicher bestätigt werden: ${native.error}`
      : "Der Kontostatus konnte nicht sicher bestätigt werden.";
    document.querySelector("#view-mode").textContent = "Nur-Lesen-Ansicht";
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
  const addable = new Set(state.native.status?.can_add_domains_to ?? []);
  let domainCount = 0;
  for (const block of rules.blocks) {
    const baseBlock = adminMode
      ? state.base_rules?.blocks.find((item) => item.id === block.id)
      : null;
    const baseDomains = new Set(baseBlock?.targets.domains ?? block.targets.domains);
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
          item.title = ownerUid
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
    if (state.native.connected && addable.has(block.id)) {
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
          showMessage(`${domain} wurde dauerhaft zu „${block.name}“ hinzugefügt.`);
          await load();
        } catch (error) {
          showMessage(error.message, true);
        } finally {
          button.disabled = false;
          setAdminBusy(false);
        }
      });
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
  } catch (error) {
    renderConnection({ connected: false, error: error.message, status: null });
    showMessage(error.message, true);
  }
}

document.querySelector("#refresh").addEventListener("click", load);
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
