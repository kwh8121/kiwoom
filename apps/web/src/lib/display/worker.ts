export function workerStatus(
  heartbeats: { aliases: string[]; seen_at: string }[],
  alias: string,
  now: Date,
): "online" | "stale" | "not_serving" {
  const matching = heartbeats.filter((heartbeat) => heartbeat.aliases.includes(alias));
  if (matching.some((heartbeat) => now.getTime() - new Date(heartbeat.seen_at).getTime() <= 45_000)) return "online";
  return matching.length ? "stale" : "not_serving";
}
