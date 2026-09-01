"use strict";

const TEST_STATUSES = ["Offen", "In Arbeit", "Bestanden", "Fehlgeschlagen", "Nicht anwendbar"];
let state = null;
let saveTimer = null;
const pendingPatches = new Map();

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

function setSaveState(text, kind = "") {
  const element = $("#save-state");
  element.textContent = text;
  element.className = `save-state ${kind}`;
}

async function loadState() {
  const response = await fetch("/api/state", { cache: "no-store" });
  if (!response.ok) throw new Error("Teststand konnte nicht geladen werden");
  state = await response.json();
  renderAll();
  setSaveState("Alle Änderungen gespeichert", "saved");
}

async function refreshIfChanged(force = false) {
  if (pendingPatches.size) return;
  const response = await fetch("/api/state", { cache: "no-store" });
  if (!response.ok) throw new Error("Teststand konnte nicht aktualisiert werden");
  const updated = await response.json();
  if (force || !state || updated.revision !== state.revision) {
    state = updated;
    renderAll();
  }
  setSaveState("Alle Änderungen gespeichert", "saved");
}

async function patch(path, changes) {
  setSaveState("Wird gespeichert …", "saving");
  const response = await fetch(path, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", "X-UPCTest-Request": "1" },
    body: JSON.stringify(changes),
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || "Speichern fehlgeschlagen");
  state = payload;
  renderSummary();
  if (!pendingPatches.size) setSaveState("Alle Änderungen gespeichert", "saved");
}

function schedulePatch(path, changes) {
  clearTimeout(saveTimer);
  pendingPatches.set(path, { ...(pendingPatches.get(path) || {}), ...changes });
  setSaveState("Änderungen warten …", "saving");
  saveTimer = setTimeout(flushPatches, 450);
}

async function flushPatches() {
  clearTimeout(saveTimer);
  while (pendingPatches.size) {
    const [path, changes] = pendingPatches.entries().next().value;
    pendingPatches.delete(path);
    try {
      await patch(path, changes);
    } catch (error) {
      pendingPatches.set(path, { ...changes, ...(pendingPatches.get(path) || {}) });
      setSaveState(error.message, "error");
      return;
    }
  }
  setSaveState("Alle Änderungen gespeichert", "saved");
}

function renderSummary() {
  const summary = state.summary;
  const handled = summary.Gesamt - summary.Offen;
  const percent = summary.Gesamt ? Math.round((handled / summary.Gesamt) * 100) : 0;
  $("#progress-percent").textContent = `${percent} %`;
  $("#progress-label").textContent = `${handled} von ${summary.Gesamt} bearbeitet`;
  $("#progress-bar").style.width = `${percent}%`;
  const labels = ["Bestanden", "Fehlgeschlagen", "In Arbeit", "Offen", "Nicht anwendbar"];
  $("#metrics").replaceChildren(...labels.map((label) => {
    const element = document.createElement("div");
    element.className = "metric";
    const strong = document.createElement("strong");
    strong.textContent = summary[label];
    const span = document.createElement("span");
    span.textContent = label;
    element.append(strong, span);
    return element;
  }));
}

function statusButton(test, status) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `status-button${test.status === status ? " selected" : ""}`;
  button.textContent = status;
  button.addEventListener("click", async () => {
    try {
      await flushPatches();
      await patch(`/api/tests/${test.id}`, { status });
      if ($("#status-filter").value) {
        renderTests();
      } else {
        const card = button.closest(".test-card");
        const badge = $(".badge.status", card);
        badge.textContent = status;
        badge.dataset.status = status;
        $$(".status-button", card).forEach((item) => {
          item.classList.toggle("selected", item.textContent === status);
        });
      }
    } catch (error) {
      setSaveState(error.message, "error");
    }
  });
  return button;
}

function activateView(name) {
  $$(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.view === name));
  $$(".view").forEach((view) => view.classList.toggle("active", view.id === `${name}-view`));
}

function openIssue(issueId) {
  activateView("issues");
  requestAnimationFrame(() => {
    const card = $(`[data-issue-id="${issueId}"]`);
    if (!card) return;
    card.scrollIntoView({ behavior: "smooth", block: "start" });
    card.classList.add("linked-target");
    setTimeout(() => card.classList.remove("linked-target"), 1800);
  });
}

function renderTests() {
  const search = $("#test-search").value.trim().toLocaleLowerCase("de");
  const status = $("#status-filter").value;
  const account = $("#account-filter").value;
  const tests = state.tests.filter((test) => {
    const haystack = [test.id, test.area, test.subsection, test.account, test.expected, test.actual, test.note]
      .join(" ").toLocaleLowerCase("de");
    return (!search || haystack.includes(search)) && (!status || test.status === status) && (!account || test.account === account);
  });
  const list = $("#test-list");
  list.replaceChildren();
  if (!tests.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "Keine Testfälle passen zu diesem Filter.";
    list.append(empty);
    return;
  }
  for (const test of tests) {
    const fragment = $("#test-template").content.cloneNode(true);
    const card = $(".test-card", fragment);
    $(".test-id", card).textContent = test.id;
    $(".test-title", card).textContent = test.expected;
    $(".account", card).textContent = test.account;
    const statusBadge = $(".status", card);
    statusBadge.textContent = test.status;
    statusBadge.dataset.status = test.status;
    $(".path", card).textContent = [test.area, test.subsection, test.priority].filter(Boolean).join(" · ");
    const detail = $(".card-detail", card);
    const summary = $(".card-summary", card);
    summary.addEventListener("click", () => {
      const expanded = summary.getAttribute("aria-expanded") === "true";
      summary.setAttribute("aria-expanded", String(!expanded));
      detail.hidden = expanded;
    });
    const actions = $(".status-actions", card);
    actions.replaceChildren(...TEST_STATUSES.map((value) => statusButton(test, value)));
    const linkedIssues = state.issues.filter((issue) => issue.test_id === test.id);
    const issueList = $(".issue-link-list", card);
    if (linkedIssues.length) {
      issueList.replaceChildren(...linkedIssues.map((issue) => {
        const link = document.createElement("button");
        link.type = "button";
        link.className = "issue-link";
        link.textContent = `${issue.id} · ${issue.status}`;
        link.addEventListener("click", () => openIssue(issue.id));
        return link;
      }));
    } else {
      const empty = document.createElement("span");
      empty.className = "muted";
      empty.textContent = "Noch keine";
      issueList.append(empty);
    }
    const createLinkedIssue = $(".create-linked-issue", card);
    createLinkedIssue.addEventListener("click", async () => {
      createLinkedIssue.disabled = true;
      try {
        await createIssue(test.id);
      } catch (error) {
        setSaveState(error.message, "error");
        createLinkedIssue.disabled = false;
      }
    });
    const actual = $(".actual", card);
    actual.value = test.actual;
    actual.addEventListener("input", () => schedulePatch(`/api/tests/${test.id}`, { actual: actual.value }));
    actual.addEventListener("change", flushPatches);
    const note = $(".note", card);
    note.value = test.note;
    note.addEventListener("input", () => schedulePatch(`/api/tests/${test.id}`, { note: note.value }));
    note.addEventListener("change", flushPatches);
    list.append(card);
  }
}

function makeField(label, value, onInput, options = null) {
  const wrapper = document.createElement("label");
  wrapper.append(document.createTextNode(label));
  const control = options ? document.createElement("select") : document.createElement("textarea");
  if (options) {
    for (const optionValue of options) {
      const option = document.createElement("option");
      option.textContent = optionValue;
      option.value = optionValue;
      control.append(option);
    }
  } else {
    control.rows = 2;
  }
  control.value = value;
  control.addEventListener("input", () => onInput(control.value));
  control.addEventListener("change", flushPatches);
  wrapper.append(control);
  return wrapper;
}

function renderIssues() {
  const list = $("#issue-list");
  list.replaceChildren();
  for (const issue of state.issues) {
    const card = document.createElement("article");
    card.className = "card issue-card";
    card.dataset.issueId = issue.id;
    const title = document.createElement("h3");
    title.textContent = `${issue.id} · ${issue.title || "Ohne Titel"}`;
    const grid = document.createElement("div");
    grid.className = "issue-grid";
    const update = (field, value) => schedulePatch(`/api/issues/${issue.id}`, { [field]: value });
    grid.append(
      makeField("Testfall", issue.test_id, (value) => update("test_id", value)),
      makeField("Schweregrad", issue.severity, (value) => update("severity", value), ["Niedrig", "Mittel", "Hoch", "Kritisch"]),
      makeField("Status", issue.status, (value) => update("status", value), ["Offen", "Behoben", "Zurückgestellt"]),
    );
    for (const [field, label] of [["title", "Titel"], ["reproduction", "Reproduktion"], ["expected", "Erwartet"], ["actual", "Tatsächlich"], ["comment", "Kommentar / Behebung"]]) {
      const wrapper = makeField(label, issue[field], (value) => update(field, value));
      wrapper.classList.add("wide");
      if (field === "comment") {
        wrapper.classList.add("issue-comment");
        const textarea = $("textarea", wrapper);
        textarea.rows = 3;
        textarea.placeholder = "Was wurde geändert und wie wurde die Behebung geprüft?";
      }
      grid.append(wrapper);
    }
    card.append(title, grid);
    list.append(card);
  }
}

async function createIssue(testId = "") {
  await flushPatches();
  const response = await fetch("/api/issues", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-UPCTest-Request": "1" },
    body: JSON.stringify({ test_id: testId }),
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || "Fehler konnte nicht angelegt werden");
  state = payload;
  renderAll();
  const issue = state.issues.at(-1);
  setSaveState(testId ? `Fehler ${issue.id} mit ${testId} verknüpft` : `Fehler ${issue.id} angelegt`, "saved");
  openIssue(issue.id);
}

function renderCommands() {
  const list = $("#command-list");
  list.replaceChildren();
  for (const command of state.commands) {
    const card = document.createElement("article");
    card.className = "card command-card";
    const head = document.createElement("div");
    head.className = "command-head";
    const heading = document.createElement("div");
    const title = document.createElement("h3");
    title.textContent = `${command.id} · ${command.area}`;
    const sub = document.createElement("p");
    sub.textContent = [command.subsection, command.kind].filter(Boolean).join(" · ");
    heading.append(title, sub);
    const copy = document.createElement("button");
    copy.type = "button";
    copy.className = "status-button copy-button";
    copy.textContent = "Kopieren";
    copy.addEventListener("click", async () => {
      await navigator.clipboard.writeText(command.command);
      copy.textContent = "Kopiert";
      setTimeout(() => { copy.textContent = "Kopieren"; }, 1200);
    });
    head.append(heading, copy);
    const pre = document.createElement("pre");
    const code = document.createElement("code");
    code.textContent = command.command;
    pre.append(code);
    const result = makeField("Ergebnis / Notiz", command.result, (value) => schedulePatch(`/api/commands/${command.id}`, { result: value }));
    card.append(head, pre, result);
    list.append(card);
  }
}

function renderEnvironment() {
  const form = $("#environment-form");
  form.replaceChildren();
  for (const [label, value] of Object.entries(state.environment)) {
    const wrapper = document.createElement("label");
    wrapper.append(document.createTextNode(label));
    const input = document.createElement("input");
    input.value = value;
    input.addEventListener("input", () => schedulePatch("/api/environment", { [label]: input.value }));
    input.addEventListener("change", flushPatches);
    wrapper.append(input);
    form.append(wrapper);
  }
}

function renderAll() {
  renderSummary();
  const accounts = [...new Set(state.tests.map((test) => test.account))].sort((a, b) => a.localeCompare(b, "de"));
  const select = $("#account-filter");
  select.replaceChildren(new Option("Alle", ""), ...accounts.map((account) => new Option(account, account)));
  renderTests();
  renderIssues();
  renderCommands();
  renderEnvironment();
}

for (const tab of $$(".tab")) {
  tab.addEventListener("click", () => activateView(tab.dataset.view));
}
$("#test-search").addEventListener("input", renderTests);
$("#status-filter").addEventListener("change", renderTests);
$("#account-filter").addEventListener("change", renderTests);
$("#add-issue").addEventListener("click", () => createIssue().catch((error) => setSaveState(error.message, "error")));
$("#refresh-button").addEventListener("click", () => refreshIfChanged(true).catch((error) => setSaveState(error.message, "error")));
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) refreshIfChanged().catch((error) => setSaveState(error.message, "error"));
});
setInterval(() => {
  if (!document.hidden) refreshIfChanged().catch((error) => setSaveState(error.message, "error"));
}, 15_000);

loadState().catch((error) => setSaveState(error.message, "error"));
