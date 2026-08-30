"use strict";

globalThis.UPC_SCHEDULE_MODEL = (() => {
  const WEEKDAYS = Object.freeze([
    Object.freeze(["MO", "Mo"]),
    Object.freeze(["TU", "Di"]),
    Object.freeze(["WE", "Mi"]),
    Object.freeze(["TH", "Do"]),
    Object.freeze(["FR", "Fr"]),
    Object.freeze(["SA", "Sa"]),
    Object.freeze(["SU", "So"]),
  ]);
  const DAY_CODES = WEEKDAYS.map(([code]) => code);
  const RRULE_PREFIX = "FREQ=WEEKLY;BYDAY=";
  const LOCAL_TIME = /^(?:[01][0-9]|2[0-3]):[0-5][0-9]$/;

  function parseRrule(rrule) {
    if (typeof rrule !== "string" || !rrule.startsWith(RRULE_PREFIX)) {
      throw new Error("Zeitfenster enthält keine unterstützte Wochenregel.");
    }
    const days = rrule.slice(RRULE_PREFIX.length).split(",");
    if (
      !days.length
      || days.some((day) => !DAY_CODES.includes(day))
      || new Set(days).size !== days.length
    ) {
      throw new Error("Zeitfenster enthält ungültige oder doppelte Wochentage.");
    }
    return new Set(days);
  }

  function scheduleFromDrafts(timezoneValue, drafts) {
    if (!Array.isArray(drafts) || !drafts.length) return null;
    const timezone = String(timezoneValue ?? "").trim();
    if (!timezone) throw new Error("Der Zeitplan benötigt eine IANA-Zeitzone.");
    const windows = drafts.map((draft, index) => {
      const selected = new Set(Array.isArray(draft.days) ? draft.days : []);
      const days = DAY_CODES.filter((day) => selected.has(day));
      if (!days.length) {
        throw new Error(`Zeitfenster ${index + 1} benötigt mindestens einen Wochentag.`);
      }
      if (selected.size !== days.length) {
        throw new Error(`Zeitfenster ${index + 1} enthält einen ungültigen Wochentag.`);
      }
      if (!LOCAL_TIME.test(draft.start) || !LOCAL_TIME.test(draft.end)) {
        throw new Error(`Zeitfenster ${index + 1} benötigt eine Start- und Endzeit.`);
      }
      return {
        start: draft.start,
        end: draft.end,
        rrule: `${RRULE_PREFIX}${days.join(",")}`,
      };
    });
    const unique = new Set(windows.map((window) => JSON.stringify(window)));
    if (unique.size !== windows.length) {
      throw new Error("Identische Zeitfenster dürfen nicht doppelt eingetragen werden.");
    }
    return { timezone, windows };
  }

  return { WEEKDAYS, parseRrule, scheduleFromDrafts };
})();
