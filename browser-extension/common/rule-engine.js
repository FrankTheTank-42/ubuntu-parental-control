"use strict";

// Browser-neutral rule compiler. It deliberately exposes one global so the
// same source works in Firefox background workers and Chrome MV3 workers.
globalThis.UPC_RULE_ENGINE = (() => {
  const DAY_CODES = ["SU", "MO", "TU", "WE", "TH", "FR", "SA"];
  const MAX_DYNAMIC_RULES = 5000;

  function assert(condition, message) {
    if (!condition) throw new Error(message);
  }

  function stableStringify(value) {
    if (Array.isArray(value)) return `[${value.map(stableStringify).join(",")}]`;
    if (value && typeof value === "object") {
      return `{${Object.keys(value)
        .sort()
        .map((key) => `${JSON.stringify(key)}:${stableStringify(value[key])}`)
        .join(",")}}`;
    }
    return JSON.stringify(value);
  }

  async function sha256(text) {
    const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
    return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
  }

  async function parseManagedSnapshot(managed) {
    assert(managed && managed.protocol_version === 1, "Managed-Policy-Protokoll fehlt oder ist unbekannt");
    assert(typeof managed.snapshot_json === "string", "Managed-Regelsnapshot fehlt");
    assert(managed.snapshot_json.length <= 1_000_000, "Managed-Regelsnapshot ist zu groß");
    let snapshot;
    try {
      snapshot = JSON.parse(managed.snapshot_json);
    } catch (error) {
      throw new Error(`Managed-Regelsnapshot ist kein JSON: ${error.message}`);
    }
    assert(snapshot && snapshot.protocol_version === 1, "Snapshot-Protokoll ist unbekannt");
    assert(typeof snapshot.revision === "string" && /^[0-9a-f]{64}$/.test(snapshot.revision), "Revision ist ungültig");
    assert(snapshot.revision === managed.revision, "Revision und Snapshot stimmen nicht überein");
    assert(snapshot.rules && typeof snapshot.rules === "object", "Regeln fehlen im Snapshot");
    const digest = await sha256(stableStringify(snapshot.rules));
    assert(digest === snapshot.revision, "Prüfsumme des Regelsnapshots stimmt nicht");
    validateRules(snapshot.rules);
    return snapshot;
  }

  function validateRules(rules) {
    assert(rules.format_version === "1.0", "Nicht unterstützte Regelversion");
    assert(rules.profile && ["allow", "block"].includes(rules.profile.default_action), "default_action ist ungültig");
    assert(rules.profile.conflict_policy === "priority_then_deny", "Konfliktstrategie ist ungültig");
    assert(Array.isArray(rules.blocks) && rules.blocks.length <= 1000, "Blocks sind ungültig");
    for (const block of rules.blocks) {
      assert(block && typeof block === "object", "Block ist ungültig");
      assert(typeof block.enabled === "boolean", `Block ${block.id ?? "?"}: enabled ist ungültig`);
      assert(Number.isInteger(block.priority) && block.priority >= -1000 && block.priority <= 1000, `Block ${block.id ?? "?"}: Priorität ist ungültig`);
      assert(["allow", "block"].includes(block.action), `Block ${block.id ?? "?"}: Aktion ist ungültig`);
      for (const groupName of ["targets", "exceptions"]) {
        const group = block[groupName];
        assert(group && Array.isArray(group.domains) && Array.isArray(group.url_patterns) && Array.isArray(group.url_regex), `Block ${block.id ?? "?"}: ${groupName} ist ungültig`);
      }
    }
  }

  function zonedParts(now, timezone) {
    const values = {};
    const parts = new Intl.DateTimeFormat("en-US", {
      timeZone: timezone,
      weekday: "short",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    }).formatToParts(now);
    for (const part of parts) values[part.type] = part.value;
    const dayMap = { Sun: "SU", Mon: "MO", Tue: "TU", Wed: "WE", Thu: "TH", Fri: "FR", Sat: "SA" };
    return { day: dayMap[values.weekday], minutes: Number(values.hour) * 60 + Number(values.minute) };
  }

  function previousDay(day) {
    const index = DAY_CODES.indexOf(day);
    return DAY_CODES[(index + 6) % 7];
  }

  function minuteValue(text) {
    const [hour, minute] = text.split(":").map(Number);
    return hour * 60 + minute;
  }

  function windowIsActive(window, local) {
    const days = window.rrule.slice("FREQ=WEEKLY;BYDAY=".length).split(",");
    const start = minuteValue(window.start);
    const end = minuteValue(window.end);
    if (end > start) return days.includes(local.day) && local.minutes >= start && local.minutes < end;
    return (
      (days.includes(local.day) && local.minutes >= start) ||
      (days.includes(previousDay(local.day)) && local.minutes < end)
    );
  }

  function blockIsActive(block, now) {
    if (!block.enabled) return false;
    if (!block.schedule) return true;
    const local = zonedParts(now, block.schedule.timezone);
    return block.schedule.windows.some((window) => windowIsActive(window, local));
  }

  function escapeRegex(text) {
    return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  function wildcardPathRegex(path) {
    return path.split("*").map(escapeRegex).join(".*");
  }

  function patternToRegex(pattern) {
    const match = /^(\*|https?):\/\/(\*|\*\.[a-z0-9.-]+|[a-z0-9.-]+)(\/.*)$/.exec(pattern);
    assert(match, `Ungültiges URL-Pattern: ${pattern}`);
    const scheme = match[1] === "*" ? "https?" : match[1];
    let host;
    if (match[2] === "*") host = "[^/:]+";
    else if (match[2].startsWith("*.")) host = `(?:[^./:]+\\.)*${escapeRegex(match[2].slice(2))}`;
    else host = escapeRegex(match[2]);
    return `^${scheme}:\\/\\/${host}(?::[0-9]+)?${wildcardPathRegex(match[3])}$`;
  }

  function dnrPriority(block) {
    // Lowest block priority is still above the packaged fail-safe priority 1.
    return 2 + (block.priority + 1000) * 2 + (block.action === "block" ? 1 : 0);
  }

  function baseCondition(excludedDomains) {
    const condition = { resourceTypes: ["main_frame", "sub_frame"] };
    if (excludedDomains.length) condition.excludedRequestDomains = excludedDomains;
    return condition;
  }

  function compile(rules, now) {
    validateRules(rules);
    const output = [];
    let id = 1;
    for (const block of rules.blocks) {
      if (!blockIsActive(block, now)) continue;
      const exceptions = block.exceptions;
      assert(
        exceptions.url_patterns.length === 0 && exceptions.url_regex.length === 0,
        `Block ${block.id}: URL-Pattern-/Regex-Ausnahmen sind mit DNR nicht verlustfrei darstellbar`,
      );
      const excluded = exceptions.domains;
      const action = { type: block.action };
      const priority = dnrPriority(block);
      for (const domain of block.targets.domains) {
        output.push({
          id: id++,
          priority,
          action,
          condition: { ...baseCondition(excluded), requestDomains: [domain] },
        });
      }
      for (const pattern of block.targets.url_patterns) {
        output.push({
          id: id++,
          priority,
          action,
          condition: {
            ...baseCondition(excluded),
            regexFilter: patternToRegex(pattern),
            // WebExtension match patterns treat the URL path as case-sensitive;
            // schemes and DNS hostnames arrive normalized by the browser.
            isUrlFilterCaseSensitive: true,
          },
        });
      }
      for (const regex of block.targets.url_regex) {
        output.push({
          id: id++,
          priority,
          action,
          condition: {
            ...baseCondition(excluded),
            regexFilter: regex.pattern,
            isUrlFilterCaseSensitive: regex.case_sensitive,
          },
        });
      }
    }
    assert(output.length <= MAX_DYNAMIC_RULES, `Zu viele dynamische Regeln: ${output.length}`);
    return { rules: output, defaultAction: rules.profile.default_action };
  }

  return { blockIsActive, compile, parseManagedSnapshot, patternToRegex, stableStringify, windowIsActive };
})();
