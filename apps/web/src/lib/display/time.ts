export function formatKst(iso: string): string {
  return `${new Date(new Date(iso).getTime() + 9 * 60 * 60 * 1000).toISOString().slice(0, 19).replace("T", " ")} KST`;
}
