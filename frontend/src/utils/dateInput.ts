// Shared parsing/formatting for the manual date field used in the email drawers.
//
// The user types a date as `DD/MM/YYYY HH:MM` with an optional trailing GMT
// offset (e.g. `19/03/2021 14:47 GMT+8` or `... GMT+05:30`). Blank is allowed.
// We canonicalize a valid entry to an ISO-8601 string for the backend, which
// re-parses it (a naive value is interpreted in the matter's default timezone;
// one with an offset keeps it).

export const DATE_INPUT_PLACEHOLDER = "DD/MM/YYYY HH:MM";

export const DATE_INPUT_HINT =
  "Format: DD/MM/YYYY HH:MM (24-hour). Optional timezone as GMT offset, e.g. 19/03/2021 14:47 GMT+8. Leave blank if unknown.";

export type DateParseResult =
  | { ok: true; value: string | null }
  | { ok: false; error: string };

const DATE_INPUT_RE =
  /^(\d{1,2})\/(\d{1,2})\/(\d{4})[ T](\d{1,2}):(\d{2})(?:\s*GMT\s*([+-])\s*(\d{1,2})(?::?(\d{2}))?)?$/i;

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

/**
 * Validate a manual date entry and canonicalize it to ISO-8601.
 * Returns `{ value: null }` for blank input, or an `error` describing the fix.
 */
export function parseDateInput(raw: string): DateParseResult {
  const text = raw.trim();
  if (!text) return { ok: true, value: null };

  const match = DATE_INPUT_RE.exec(text);
  if (!match) {
    return { ok: false, error: `Enter the date as ${DATE_INPUT_PLACEHOLDER}, or leave it blank.` };
  }

  const [, dd, mm, yyyy, hh, min, sign, offHours, offMinutes] = match;
  const day = Number(dd);
  const month = Number(mm);
  const year = Number(yyyy);
  const hour = Number(hh);
  const minute = Number(min);

  if (month < 1 || month > 12) return { ok: false, error: "Month must be between 01 and 12." };
  if (day < 1 || day > 31) return { ok: false, error: "Day must be between 01 and 31." };
  if (hour > 23) return { ok: false, error: "Hour must be between 00 and 23." };
  if (minute > 59) return { ok: false, error: "Minutes must be between 00 and 59." };

  // Reject dates that don't exist on the calendar (e.g. 31/02/2021).
  const probe = new Date(Date.UTC(year, month - 1, day));
  if (probe.getUTCMonth() !== month - 1 || probe.getUTCDate() !== day) {
    return { ok: false, error: "That date does not exist on the calendar." };
  }

  let iso = `${year}-${pad(month)}-${pad(day)}T${pad(hour)}:${pad(minute)}:00`;

  if (sign) {
    const offH = Number(offHours);
    const offM = offMinutes ? Number(offMinutes) : 0;
    if (offH > 14 || offM > 59) return { ok: false, error: "GMT offset is out of range." };
    iso += `${sign}${pad(offH)}:${pad(offM)}`;
  }

  return { ok: true, value: iso };
}

/**
 * Render a stored instant back into the `DD/MM/YYYY HH:MM GMT±HH:MM` form so
 * editing round-trips. The wall-clock time is shown in `timeZone` (the matter's
 * default), with an explicit offset so the value re-parses unambiguously.
 */
export function formatDateInput(value?: string | null, timeZone?: string): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;

  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    timeZoneName: "longOffset"
  }).formatToParts(date);

  const get = (type: string) => parts.find((part) => part.type === type)?.value ?? "";
  const tzName = get("timeZoneName"); // "GMT+08:00", "GMT-05:00" or "UTC"
  const offsetMatch = /GMT([+-]\d{2}:?\d{2})/.exec(tzName);
  const offset = offsetMatch ? offsetMatch[1].replace(/(\d{2})(\d{2})$/, "$1:$2") : "+00:00";

  return `${get("day")}/${get("month")}/${get("year")} ${get("hour")}:${get("minute")} GMT${offset}`;
}
