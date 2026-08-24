/**
 * Times as a family says them.
 *
 * Everything is stored and sent as 24-hour "HH:MM" because that is unambiguous
 * between a browser, an API and a database. None of that is true of the person
 * reading the screen, who thinks in half six in the evening.
 */

/** "18:35" -> "6:35 pm". Returns the input unchanged if it is not a time. */
export function clockTime(value: string): string {
  const [hours, minutes] = value.split(":").map(Number);
  if (!Number.isInteger(hours) || !Number.isInteger(minutes)) return value;

  const suffix = hours < 12 ? "am" : "pm";
  const hour12 = hours % 12 === 0 ? 12 : hours % 12;
  return `${hour12}:${String(minutes).padStart(2, "0")} ${suffix}`;
}

/** What the clock says where they are, right now: "12:37 am".
 *  Empty when the zone cannot be resolved, so callers can just test it. */
export function timeIn(timezone: string): string {
  try {
    return new Intl.DateTimeFormat("en-GB", {
      hour: "numeric",
      minute: "2-digit",
      hour12: true,
      timeZone: timezone,
    })
      .format(new Date())
      .toLowerCase();
  } catch {
    return "";
  }
}

/** "2 minutes ago", for a phone's last contact. Vague on purpose past a day:
 *  what a family wants to know is whether it is still switched on. */
export function sinceWhen(value: string | null): string {
  if (!value) return "never";

  const then = new Date(value).getTime();
  if (Number.isNaN(then)) return "never";

  const minutes = Math.round((Date.now() - then) / 60000);
  if (minutes < 2) return "just now";
  if (minutes < 60) return `${minutes} minutes ago`;

  const hours = Math.round(minutes / 60);
  if (hours < 24) return hours === 1 ? "an hour ago" : `${hours} hours ago`;

  const days = Math.round(hours / 24);
  return days === 1 ? "yesterday" : `${days} days ago`;
}
