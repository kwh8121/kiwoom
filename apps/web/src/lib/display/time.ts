export function formatKst(iso: string): string {
  return `${new Date(new Date(iso).getTime() + 9 * 60 * 60 * 1000).toISOString().slice(0, 19).replace("T", " ")} KST`;
}

// The closure calendar is keyed on the KST trading day, which is already the
// next date in Seoul for anything from 15:00 UTC onward. Returns null for a
// value it cannot read, because the caller passes a column straight in and a
// throw would turn an unreadable timestamp into a failed page.
export function kstDate(iso: string | null): string | null {
  if (iso === null) return null;
  const shifted = new Date(iso).getTime() + 9 * 60 * 60 * 1000;
  if (Number.isNaN(shifted)) return null;
  return new Date(shifted).toISOString().slice(0, 10);
}
