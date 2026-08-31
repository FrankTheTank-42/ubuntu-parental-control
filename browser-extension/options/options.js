"use strict";

const api = globalThis.browser ?? globalThis.chrome;
const isFirefox = typeof globalThis.browser !== "undefined";
const blocksElement = document.querySelector("#blocks");
const rowTemplate = document.querySelector("#block-row-template");
const detailTemplate = document.querySelector("#block-detail-template");
const messageElement = document.querySelector("#message");
const { WEEKDAYS, parseRrule, scheduleFromDrafts } = globalThis.UPC_SCHEDULE_MODEL;
const { sortedBlocks, moveBlock, prioritiesForOrder } = globalThis.UPC_ORDER_MODEL;
let currentState = null;
let adminBusy = false;
let selectedBlockId = null;
let draggedBlockId = null;
let draftRules = null;
let draftDirty = false;
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
  connection.hidden = false;
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
  if (native.status.role === "restricted") {
    title.textContent = "Eingeschränktes Konto verbunden";
    detail.textContent = "Du kannst jede Blockierliste um Domains ergänzen. Löschen und Lockern ist nicht möglich.";
    document.querySelector("#view-mode").textContent = "Kinderansicht";
  } else {
    document.querySelector("#view-mode").textContent = "Elternansicht";
    connection.hidden = true;
  }
}

function scheduleText(block) {
  if (!block.schedule) return "durchgehend aktiv";
  const count = block.schedule.windows.length;
  return `${count} Zeitfenster · ${block.schedule.timezone}`;
}

function updateScheduleRows(form) {
  const rows = [...form.querySelectorAll(".schedule-window")];
  rows.forEach((row, index) => {
    row.querySelector(".schedule-window-title").textContent = `Zeitfenster ${index + 1}`;
  });
  form.querySelector(".schedule-empty").hidden = rows.length > 0;
  form.querySelector(".schedule-overnight-note").hidden = rows.length === 0;
}

function addScheduleWindowRow(form, window = null) {
  const selectedDays = window
    ? parseRrule(window.rrule)
    : new Set(["MO", "TU", "WE", "TH", "FR"]);
  const row = document.createElement("section");
  row.className = "schedule-window";

  const heading = document.createElement("div");
  heading.className = "schedule-window-heading";
  const title = document.createElement("strong");
  title.className = "schedule-window-title";
  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "secondary remove-window";
  remove.textContent = "Entfernen";
  remove.addEventListener("click", () => {
    row.remove();
    updateScheduleRows(form);
  });
  heading.append(title, remove);

  const days = document.createElement("div");
  days.className = "schedule-days";
  days.setAttribute("aria-label", "Wochentage");
  for (const [code, label] of WEEKDAYS) {
    const day = document.createElement("label");
    day.className = "schedule-day";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.dataset.day = code;
    checkbox.checked = selectedDays.has(code);
    const text = document.createElement("span");
    text.textContent = label;
    day.append(checkbox, text);
    days.append(day);
  }

  const times = document.createElement("div");
  times.className = "schedule-times";
  for (const [className, label, value] of [
    ["schedule-start", "Von", window?.start ?? "18:00"],
    ["schedule-end", "Bis", window?.end ?? "20:00"],
  ]) {
    const timeLabel = document.createElement("label");
    timeLabel.textContent = label;
    const input = document.createElement("input");
    input.className = className;
    input.type = "time";
    input.step = "60";
    input.required = true;
    input.value = value;
    timeLabel.append(input);
    times.append(timeLabel);
  }

  row.append(heading, days, times);
  form.querySelector(".schedule-windows").append(row);
  updateScheduleRows(form);
}

function setupScheduleEditor(form, schedule, profileTimezone) {
  const timezone = form.querySelector(".admin-schedule-timezone");
  timezone.value = schedule?.timezone ?? profileTimezone ?? "Europe/Berlin";
  const windows = form.querySelector(".schedule-windows");
  windows.replaceChildren();
  for (const window of schedule?.windows ?? []) addScheduleWindowRow(form, window);
  form.querySelector(".add-window").addEventListener("click", () => {
    addScheduleWindowRow(form);
  });
  updateScheduleRows(form);
}

function readScheduleEditor(form) {
  const rows = [...form.querySelectorAll(".schedule-window")];
  const timezone = form.querySelector(".admin-schedule-timezone").value.trim();
  const drafts = rows.map((row) => ({
    days: WEEKDAYS
      .filter(([code]) => row.querySelector(`input[data-day="${code}"]`).checked)
      .map(([code]) => code),
    start: row.querySelector(".schedule-start").value,
    end: row.querySelector(".schedule-end").value,
  }));
  return scheduleFromDrafts(timezone, drafts);
}

function lines(value) {
  return value.split("\n").map((item) => item.trim()).filter(Boolean);
}

function domainLines(value) {
  const domainPattern = /^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/;
  const domains = [...new Set(lines(value).map((item) => item.toLowerCase()))];
  const invalid = domains.find((domain) => domain.length > 253 || !domainPattern.test(domain));
  if (invalid) {
    throw new Error(`Ungültige Domain „${invalid}“. Bitte ohne Protokoll, Pfad oder Port eingeben.`);
  }
  return domains;
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
    ".admin-form button, #create-block, #save-all, #discard-draft, .reorder-buttons button, .remove-user-domain, .remove-base-domain, .show-domain-add, .domain-add-panel button",
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
  if (typeof currentState?.base_revision !== "string") {
    throw new Error("Aktuelle Basisrevision fehlt; bitte Regeln neu laden.");
  }
  await runAdminOperation(
    () => send({
      type: "admin_apply",
      rules,
      expected_base_revision: currentState.base_revision,
    }),
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
  if (state.native.status.role === "restricted") {
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
  const baseBlock = draftRules?.blocks.find((item) => item.id === block.id);
  if (!baseBlock || baseBlock.action !== "block") {
    throw new Error("Die ausgewählte Blockierliste ist administrativ nicht verfügbar.");
  }
  baseBlock.targets.domains.push(addition.domain);
  baseBlock.targets.domains.sort();
  markDraftDirty(`${addition.domain} wurde zum Entwurf von „${baseBlock.name}“ hinzugefügt.`);
  selectedBlockId = block.id;
  renderBlocks(state);
  openDetail(block.id);
}

function displayedRules(state = currentState) {
  return modes(state).admin && draftRules ? draftRules : state.rules;
}

function updateDraftBar() {
  document.querySelector("#draft-bar").hidden = !draftDirty;
}

function markDraftDirty(message = "Änderung wurde in den Entwurf übernommen.") {
  draftDirty = true;
  updateDraftBar();
  showMessage(message);
}

function resetDraft() {
  draftRules = currentState?.base_rules ? structuredClone(currentState.base_rules) : null;
  draftDirty = false;
  updateDraftBar();
}

function updateBlockFromForm(form, rules, blockId) {
  const index = rules.blocks.findIndex((item) => item.id === blockId);
  if (index < 0) throw new Error("Der Block ist im aktuellen Entwurf nicht mehr vorhanden.");
  const previous = rules.blocks[index];
  const edited = structuredClone(previous);
  const newName = form.querySelector(".admin-name").value.trim();
  if (!newName) throw new Error("Der Block benötigt einen Namen.");
  const duplicate = rules.blocks.find(
    (item) => item.id !== blockId
      && normalizedBlockName(item.name) === normalizedBlockName(newName),
  );
  if (duplicate) {
    throw new Error(`Der Name „${duplicate.name}“ wird bereits von Block ${duplicate.id} verwendet.`);
  }
  edited.name = newName;
  edited.enabled = form.querySelector(".admin-enabled").checked;
  edited.action = form.querySelector(".admin-action").value;
  edited.user_permissions.add_domains = edited.action === "block";
  edited.targets.url_patterns = lines(form.querySelector(".admin-patterns").value);
  edited.targets.url_regex = parseRegexLines(form.querySelector(".admin-regex").value);
  edited.exceptions.domains = lines(form.querySelector(".admin-exceptions").value);
  const schedule = readScheduleEditor(form);
  if (schedule) edited.schedule = schedule;
  else delete edited.schedule;
  const changed = JSON.stringify(previous) !== JSON.stringify(edited);
  if (changed) rules.blocks[index] = edited;
  return { edited, changed };
}

function stageOpenDetail() {
  if (!selectedBlockId || !modes(currentState).admin || !draftRules) return true;
  const form = document.querySelector("#detail-container .admin-form");
  if (!form || form.classList.contains("locked")) return true;
  if (!form.reportValidity()) return false;
  try {
    const { edited, changed } = updateBlockFromForm(form, draftRules, selectedBlockId);
    if (changed) markDraftDirty(`„${edited.name}“ wurde in den Entwurf übernommen.`);
    return stageOpenDomainPanel();
  } catch (error) {
    showMessage(error.message, true);
    return false;
  }
}

function stageOpenDomainPanel() {
  const panel = document.querySelector("#detail-container .domain-add-panel");
  if (!panel || panel.hidden) return true;
  const input = panel.querySelector(".domain-add-input");
  if (!input.value.trim()) return true;
  try {
    const additions = domainLines(input.value);
    const block = draftRules?.blocks.find((item) => item.id === selectedBlockId);
    if (!block) throw new Error("Der Block ist im aktuellen Entwurf nicht mehr vorhanden.");
    const previous = new Set(block.targets.domains);
    block.targets.domains = [...new Set([...block.targets.domains, ...additions])].sort();
    const added = block.targets.domains.length - previous.size;
    input.value = "";
    if (added) markDraftDirty(`${added} Domain${added === 1 ? "" : "s"} zum Entwurf hinzugefügt.`);
    else showMessage("Diese Domains sind bereits im Block enthalten.");
    return true;
  } catch (error) {
    showMessage(error.message, true);
    return false;
  }
}

function setupAdminForm(card, block, baseRules, editable, profileTimezone) {
  const form = card.querySelector(".admin-form");
  form.hidden = false;
  form.querySelector(".admin-name").value = block.name;
  form.querySelector(".admin-enabled").checked = block.enabled;
  form.querySelector(".admin-action").value = block.action;
  form.querySelector(".admin-patterns").value = block.targets.url_patterns.join("\n");
  form.querySelector(".admin-regex").value = regexLines(block.targets.url_regex);
  form.querySelector(".admin-exceptions").value = block.exceptions.domains.join("\n");
  setupScheduleEditor(form, block.schedule, profileTimezone);
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
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    try {
      const { edited, changed } = updateBlockFromForm(form, baseRules, block.id);
      if (changed) markDraftDirty(`„${edited.name}“ wurde in den Entwurf übernommen.`);
      else showMessage("An diesem Block wurden keine Änderungen vorgenommen.");
    } catch (error) {
      showMessage(error.message, true);
    }
  });
  card.querySelector(".delete-block").addEventListener("click", () => {
    if (!confirm(`Block „${block.name}“ wirklich löschen?`)) return;
    baseRules.blocks = baseRules.blocks.filter((item) => item.id !== block.id);
    markDraftDirty(`„${block.name}“ wurde im Entwurf gelöscht.`);
    showOverview();
    renderBlocks(currentState);
  });
}

function modes(state) {
  const admin = Boolean(state.native.connected && state.native.status?.role === "administrator");
  const child = Boolean(state.native.connected && state.native.status?.role === "restricted");
  return { admin, child };
}

function fillBadges(container, block) {
  container.append(
    badge(block.action === "block" ? "Blockieren" : "Erlauben", block.action),
    badge(block.enabled ? "Aktiv" : "Inaktiv", block.enabled ? "" : "inactive"),
  );
}

function stageOrder(blockId, offset) {
  if (!modes(currentState).admin || adminBusy || !draftRules) return;
  const ordered = moveBlock(draftRules.blocks, blockId, offset);
  prioritiesForOrder(ordered).forEach(({ id, priority }) => {
    draftRules.blocks.find((block) => block.id === id).priority = priority;
  });
  draftRules.blocks = ordered;
  markDraftDirty("Die neue Block-Reihenfolge ist im Entwurf sichtbar.");
  renderBlocks(currentState);
  document.querySelector(`[data-block-id="${CSS.escape(blockId)}"]`)?.focus();
}

function openDetail(blockId) {
  selectedBlockId = blockId;
  renderDetail(currentState);
  document.querySelector("#overview-view").hidden = true;
  document.querySelector("#detail-view").hidden = false;
  document.querySelector("#page-subtitle").textContent = "Ziele, Ausnahmen und Zeitfenster bearbeiten.";
  document.querySelector("#back-to-overview").focus();
}

function renderOverview(state) {
  const { admin, child } = modes(state);
  const editable = admin && Boolean(state.base_rules);
  const rules = displayedRules(state);
  blocksElement.replaceChildren();
  for (const [index, block] of sortedBlocks(rules.blocks).entries()) {
    const row = rowTemplate.content.firstElementChild.cloneNode(true);
    row.dataset.blockId = block.id;
    row.draggable = editable;
    row.querySelector(".block-name").textContent = block.name;
    row.querySelector(".block-id").textContent = block.id;
    row.querySelector(".priority-label").textContent = `Priorität ${block.priority}`;
    fillBadges(row.querySelector(".badges"), block);
    row.querySelector(".block-open").addEventListener("click", () => openDetail(block.id));
    row.addEventListener("dblclick", () => openDetail(block.id));
    const up = row.querySelector(".move-up");
    const down = row.querySelector(".move-down");
    for (const button of [up, down]) {
      button.disabled = !editable;
      button.dataset.permanentlyDisabled = editable ? "false" : "true";
    }
    up.disabled ||= index === 0;
    down.disabled ||= index === rules.blocks.length - 1;
    up.addEventListener("click", () => stageOrder(block.id, -1));
    down.addEventListener("click", () => stageOrder(block.id, 1));
    row.addEventListener("keydown", (event) => {
      if (!editable || !event.altKey || !["ArrowUp", "ArrowDown"].includes(event.key)) return;
      event.preventDefault();
      stageOrder(block.id, event.key === "ArrowUp" ? -1 : 1);
    });
    row.addEventListener("dragstart", (event) => { draggedBlockId = block.id; row.classList.add("dragging"); event.dataTransfer.effectAllowed = "move"; });
    row.addEventListener("dragend", () => { draggedBlockId = null; row.classList.remove("dragging"); });
    row.addEventListener("dragover", (event) => { if (editable && draggedBlockId && draggedBlockId !== block.id) { event.preventDefault(); row.classList.add("drag-target"); } });
    row.addEventListener("dragleave", () => row.classList.remove("drag-target"));
    row.addEventListener("drop", (event) => {
      event.preventDefault(); row.classList.remove("drag-target");
      const ordered = sortedBlocks(rules.blocks); const from = ordered.findIndex((item) => item.id === draggedBlockId); const to = ordered.findIndex((item) => item.id === block.id);
      if (from >= 0 && to >= 0 && from !== to) stageOrder(draggedBlockId, to - from);
    });
    blocksElement.append(row);
  }
  const defaultRule = document.querySelector("#default-rule");
  const select = document.querySelector("#default-action");
  select.value = rules.profile.default_action;
  select.disabled = !editable;
  defaultRule.classList.toggle("locked", !editable);
  defaultRule.title = child ? "Nur ein Elternkonto kann die Abschlussregel ändern." : "";
  document.querySelector("#order-help").textContent = editable
    ? "Höchste Priorität steht oben. Zum Verschieben ziehen oder Alt+Pfeil hoch/runter verwenden."
    : "Höchste Priorität steht oben. Die Reihenfolge ist in dieser Ansicht schreibgeschützt.";
}

function renderDomains(card, state, block, baseBlock) {
  const { admin, child } = modes(state);
  const own = new Set(state.user_domains?.users?.[String(state.native.status?.uid)]?.[block.id] ?? []);
  const base = new Set(baseBlock?.targets.domains ?? block.targets.domains.filter((domain) => !own.has(domain)));
  const container = card.querySelector(".domain-list");
  for (const domain of block.targets.domains) {
    const item = document.createElement("span"); item.className = `domain ${base.has(domain) ? "" : "user-added"}`.trim(); item.textContent = domain;
    const ownerUid = base.has(domain) ? null : userDomainOwner(state, block.id, domain);
    if (!base.has(domain)) item.title = child && ownerUid === state.native.status.uid ? "Von dir ergänzt" : `Von eingeschränktem Konto UID ${ownerUid} ergänzt`;
    if (admin && base.has(domain)) {
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "remove-base-domain";
      remove.textContent = "×";
      remove.title = `${domain} aus dem Entwurf entfernen`;
      remove.setAttribute("aria-label", `${domain} entfernen`);
      remove.addEventListener("click", () => {
        if (!stageOpenDetail()) return;
        const draftBlock = draftRules?.blocks.find((entry) => entry.id === block.id);
        if (!draftBlock) return;
        draftBlock.targets.domains = draftBlock.targets.domains.filter((entry) => entry !== domain);
        markDraftDirty(`${domain} wurde im Entwurf aus „${draftBlock.name}“ entfernt.`);
        renderDetail(currentState);
      });
      item.append(remove);
    }
    if (admin && ownerUid) { const remove = document.createElement("button"); remove.type = "button"; remove.className = "remove-user-domain"; remove.textContent = "×"; remove.title = "Kinderergänzung entfernen"; remove.addEventListener("click", async () => { if (!confirm(`${domain} aus den Ergänzungen von UID ${ownerUid} entfernen?`)) return; try { await runAdminOperation(() => send({ type: "admin_remove_user_domain", uid: ownerUid, block_id: block.id, domain }), `${domain} wurde entfernt.`); } catch (error) { showMessage(error.message, true); } }); item.append(remove); }
    container.append(item);
  }
  if (!block.targets.domains.length) { const empty = document.createElement("span"); empty.className = "empty"; empty.textContent = "Keine Domain-Ziele"; container.append(empty); }
}

function renderDetail(state) {
  const rules = displayedRules(state);
  const block = rules.blocks.find((item) => item.id === selectedBlockId);
  if (!block) { selectedBlockId = null; showOverview(); return; }
  const { admin, child } = modes(state);
  const baseBlock = admin ? draftRules?.blocks.find((item) => item.id === block.id) : null;
  const card = detailTemplate.content.firstElementChild.cloneNode(true);
  card.querySelector(".block-name").textContent = block.name; card.querySelector(".block-id").textContent = `Technische ID: ${block.id}`; fillBadges(card.querySelector(".badges"), block);
  const visibleBlock = structuredClone(block);
  if (admin) {
    for (const userBlocks of Object.values(state.user_domains?.users ?? {})) {
      for (const domain of userBlocks[block.id] ?? []) {
        if (!visibleBlock.targets.domains.includes(domain)) visibleBlock.targets.domains.push(domain);
      }
    }
  }
  renderDomains(card, state, visibleBlock, baseBlock);
  if (admin && baseBlock) {
    const showAdd = card.querySelector(".show-domain-add");
    const panel = card.querySelector(".domain-add-panel");
    const input = panel.querySelector(".domain-add-input");
    showAdd.hidden = false;
    showAdd.addEventListener("click", () => {
      panel.hidden = false;
      showAdd.hidden = true;
      input.focus();
    });
    panel.querySelector(".cancel-domain-add").addEventListener("click", () => {
      input.value = "";
      panel.hidden = true;
      showAdd.hidden = false;
      showAdd.focus();
    });
    panel.addEventListener("submit", (event) => {
      event.preventDefault();
      if (!stageOpenDetail()) return;
      renderDetail(currentState);
    });
  }
  const addForm = card.querySelector(".add-domain-form");
  if (child && block.action === "block") { addForm.hidden = false; addForm.addEventListener("submit", async (event) => { event.preventDefault(); const input = addForm.querySelector(".domain-input"); const domain = input.value.trim().toLowerCase(); setAdminBusy(true); try { await send({ type: "add_domain", block_id: block.id, domain }); input.value = ""; showMessage(`${domain} wurde als geschützte Kinderergänzung gespeichert.`); await load(); } catch (error) { showMessage(error.message, true); } finally { setAdminBusy(false); } }); }
  else if (block.action === "block" && (!state.native.connected || !state.native.status)) { const unavailable = card.querySelector(".add-domain-unavailable"); unavailable.hidden = false; unavailable.querySelector(".add-domain-unavailable-detail").textContent = nativeFailure(state.native).detail; }
  setupAdminForm(card, baseBlock ?? block, draftRules, admin && Boolean(baseBlock), rules.profile.timezone);
  document.querySelector("#detail-container").replaceChildren(card);
}

function showOverview() {
  selectedBlockId = null;
  document.querySelector("#detail-view").hidden = true;
  document.querySelector("#overview-view").hidden = false;
  document.querySelector("#page-subtitle").textContent = "Blocks ordnen und Filterverhalten festlegen.";
  document.querySelector("#overview-title").focus?.();
}

function renderBlocks(state) {
  const { admin, child } = modes(state);
  document.body.classList.remove("mode-loading", "mode-parent", "mode-child", "mode-readonly");
  document.body.classList.add(admin ? "mode-parent" : child ? "mode-child" : "mode-readonly");
  if (!state.rules) { showMessage("Es ist noch kein gültiger Regelsnapshot verfügbar.", true); return; }
  const create = document.querySelector("#create-block"); create.hidden = !(admin || child); create.disabled = child; create.dataset.permanentlyDisabled = child ? "true" : "false"; create.title = child ? "Nur ein Elternkonto kann neue Blocks anlegen." : "";
  renderOverview(state);
  if (selectedBlockId) renderDetail(state);
}

async function load() {
  try {
    const state = await send({ type: "get_ui_state" });
    clearStaleError();
    currentState = state;
    resetDraft();
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

document.querySelector("#refresh").addEventListener("click", () => {
  if (draftDirty && !confirm("Ungespeicherte Änderungen verwerfen und neu laden?")) return;
  load();
});
document.querySelector("#back-to-overview").addEventListener("click", () => {
  if (!stageOpenDetail()) return;
  showOverview();
  renderBlocks(currentState);
});
document.querySelector("#default-rule").addEventListener("submit", (event) => {
  event.preventDefault();
});
document.querySelector("#default-action").addEventListener("change", (event) => {
  if (!modes(currentState).admin || !draftRules) return;
  draftRules.profile.default_action = event.target.value;
  markDraftDirty(
    event.target.value === "block"
      ? "Whitelist-Betrieb ist im Entwurf ausgewählt."
      : "Blocklisten-Betrieb ist im Entwurf ausgewählt.",
  );
});
document.querySelector("#discard-draft").addEventListener("click", () => {
  if (!confirm("Alle ungespeicherten Änderungen verwerfen?")) return;
  resetDraft();
  selectedBlockId = null;
  showOverview();
  renderBlocks(currentState);
  showMessage("Der Entwurf wurde verworfen.");
});
document.querySelector("#save-all").addEventListener("click", async () => {
  if (!draftRules || !draftDirty || !stageOpenDetail()) return;
  try {
    await applyAdminRules(structuredClone(draftRules), "Alle Änderungen wurden gespeichert.");
  } catch (error) {
    showMessage(error.message, true);
  }
});
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
  if (!draftRules) return;
  const name = prompt(
    "Wie soll der Block heißen?\n\n" +
    "Beispiel: Soziale Medien am Abend\n" +
    "Die benötigte technische ID wird automatisch daraus erzeugt.",
  )?.trim();
  if (!name) return;
  const duplicate = draftRules.blocks.find(
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
  let id;
  try {
    id = blockIdFromName(name, draftRules.blocks);
  } catch (error) {
    showMessage(error.message, true);
    return;
  }
  const highestPriority = draftRules.blocks.reduce(
    (highest, block) => Math.max(highest, block.priority),
    -1,
  );
  draftRules.blocks.push({
    id,
    name,
    enabled: true,
    priority: Math.min(1000, highestPriority + 1),
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
    targets: { domains: [], url_patterns: [], url_regex: [] },
    exceptions: { domains: [], url_patterns: [], url_regex: [] },
    limits: null,
  });
  markDraftDirty(`„${name}“ wurde als leerer Block im Entwurf angelegt.`);
  renderBlocks(currentState);
  openDetail(id);
});
window.addEventListener("beforeunload", (event) => {
  if (!draftDirty) return;
  event.preventDefault();
  event.returnValue = "";
});
load();
