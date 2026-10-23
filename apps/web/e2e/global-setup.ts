import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { createClient } from "@supabase/supabase-js";

const root = resolve(import.meta.dirname, "../../..");
let cachedStatus: Record<string, string> | undefined;

// Capture CLI output in memory only: it contains the local service role key.
function localStatus() {
  if (cachedStatus) return cachedStatus;
  let output: string;
  try {
    output = execFileSync("pnpm", ["exec", "supabase", "status", "-o", "env"], {
      cwd: root, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"],
      env: { ...process.env, DO_NOT_TRACK: "1", SUPABASE_TELEMETRY_DISABLED: "1" },
    });
  } catch {
    // Never include the captured CLI output in errors (it can contain keys).
    throw new Error("Could not read local Supabase status; check Docker and CLI permissions");
  }
  const values = Object.fromEntries(output.split("\n").flatMap(line => {
    const match = line.match(/^([A-Z_]+)="(.*)"$/);
    return match && ["API_URL", "DB_URL", "ANON_KEY", "SERVICE_ROLE_KEY"].includes(match[1])
      ? [[match[1], match[2]]] : [];
  }));
  for (const name of ["API_URL", "DB_URL"]) {
    const url = new URL(values[name]);
    if (!["127.0.0.1", "localhost"].includes(url.hostname)) throw new Error("E2E requires local Supabase");
  }
  cachedStatus = values;
  return values;
}

export function prepareEnvironment() {
  if (process.env.KIWOOM_E2E_RUNTIME) return;
  const status = localStatus();
  const id = randomUUID().replaceAll("-", "");
  const directory = mkdtempSync(resolve(tmpdir(), "kiwoom-e2e-"));
  // Covers failures before the worker wrapper starts (for example a missing uv).
  process.once("exit", () => rmSync(directory, { recursive: true, force: true }));
  const alias = `e2e-demo-${id}`;
  const profiles = resolve(directory, "profiles.toml");
  writeFileSync(profiles, `[profiles.${alias}]\nmode = "demo"\nappkey = "fixture-only"\nsecretkey = "fixture-only"\n`, { mode: 0o600 });
  Object.assign(process.env, {
    KIWOOM_E2E_RUNTIME: directory,
    E2E_EMAIL: `e2e-${id}@example.test`, E2E_PASSWORD: randomUUID(), E2E_ALIAS: alias,
    E2E_ROLE: `e2e_${id}`, E2E_ROLE_PASSWORD: randomUUID(), E2E_LOCAL_DB: status.DB_URL,
    UV_CACHE_DIR: resolve(directory, "uv-cache"),
    NEXT_PUBLIC_SUPABASE_URL: status.API_URL,
    NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: status.ANON_KEY,
    KIWOOM_WORKER_ID: `e2e-${id}`, KIWOOM_WORKER_PROFILES_FILE: profiles,
  });
}

// The wrapper owns its temporary DB login and files even when setup or tests fail.
// It grants the existing worker role without changing that role's LOGIN/password.
export const workerBootstrap = String.raw`
import os, signal, subprocess, shutil, sys, time
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
env = os.environ.copy()
admin = psycopg.connect(env.pop('E2E_LOCAL_DB'), host='127.0.0.1', hostaddr='127.0.0.1', connect_timeout=5, options='-c statement_timeout=3000', autocommit=True)
role = env.pop('E2E_ROLE')
password = env.pop('E2E_ROLE_PASSWORD')
child = None
created = False
stop_deadline = None
kill_attempted = False
def stop(*_):
    global stop_deadline
    if child is not None:
        if child.poll() is None:
            child.terminate()
            stop_deadline = time.monotonic() + 5
signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
try:
    # claim_run reaps expired leases globally; do not disturb existing jobs.
    if admin.execute("select exists(select 1 from public.runs where status='running')").fetchone()[0]:
        raise RuntimeError('E2E requires no pre-existing running jobs')
    admin.execute(sql.SQL('create role {} login inherit password {}').format(sql.Identifier(role), sql.Literal(password)))
    created = True
    admin.execute(sql.SQL('grant kiwoom_worker to {}').format(sql.Identifier(role)))
    env['KIWOOM_WORKER_DATABASE_URL'] = make_conninfo(os.environ['E2E_LOCAL_DB'], host='127.0.0.1', hostaddr='127.0.0.1', user=role, password=password, options='-c role=kiwoom_worker')
    child = subprocess.Popen(['kiwoom-worker'], env=env)
    for _ in range(100):
        if child.poll() is not None:
            raise RuntimeError('fixture worker exited during startup')
        if admin.execute('select 1 from public.worker_heartbeats where worker_id=%s', (env['KIWOOM_WORKER_ID'],)).fetchone():
            print('fixture worker ready', flush=True)
            break
        time.sleep(.1)
    else:
        raise RuntimeError('fixture heartbeat did not appear')
    while child.poll() is None:
        try:
            child.wait(timeout=.25)
        except subprocess.TimeoutExpired:
            if stop_deadline is not None and time.monotonic() >= stop_deadline:
                kill_attempted = True
                child.kill()
                try:
                    child.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    raise RuntimeError('fixture worker did not stop after kill')
    sys.exit(child.returncode)
finally:
    failures = []
    if child is not None:
        try:
            if child.poll() is None and not kill_attempted:
                child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    kill_attempted = True
                    child.kill()
                    child.wait(timeout=2)
        except Exception as exc:
            failures.append(type(exc).__name__)
    try:
        admin.execute('delete from public.worker_heartbeats where worker_id=%s', (env['KIWOOM_WORKER_ID'],))
    except Exception as exc:
        failures.append(type(exc).__name__)
    try:
        if created:
            admin.execute(sql.SQL('drop role {}').format(sql.Identifier(role)))
    except Exception as exc:
        failures.append(type(exc).__name__)
    try:
        admin.close()
    except Exception as exc:
        failures.append(type(exc).__name__)
    try:
        shutil.rmtree(env['KIWOOM_E2E_RUNTIME'], ignore_errors=False)
    except FileNotFoundError:
        pass
    except Exception as exc:
        failures.append(type(exc).__name__)
    if failures:
        raise RuntimeError(f'fixture worker cleanup failed ({len(failures)} operation(s)): {",".join(failures)}')
`;

function deleteOwnedStrategyVersions(userId: string) {
  // ALTER TABLE and targeted deletion share one transaction and its table lock.
  // Any exception rolls back, restoring the immutable trigger before other sessions proceed.
  try {
    execFileSync("uv", ["run", "--project", "apps/worker", "python", "-c", String.raw`
import json, sys, psycopg
data = json.load(sys.stdin)
with psycopg.connect(data['database'], host='127.0.0.1', hostaddr='127.0.0.1') as db:
    db.execute('alter table public.strategy_versions disable trigger strategy_versions_immutable')
    db.execute('delete from public.runs where user_id=%s', (data['user_id'],))
    db.execute('delete from public.strategy_versions where user_id=%s', (data['user_id'],))
    db.execute('alter table public.strategy_versions enable trigger strategy_versions_immutable')
`], { cwd: root, input: JSON.stringify({ database: process.env.E2E_LOCAL_DB, user_id: userId }), stdio: ["pipe", "pipe", "pipe"], env: process.env });
  } catch {
    throw new Error("Could not remove disposable E2E strategy versions");
  }
}

export default async function globalSetup() {
  if (!cachedStatus) throw new Error("Local Supabase status must be captured by the E2E config");
  const status = cachedStatus;
  const response = await fetch(`${status.API_URL}/auth/v1/settings`, { headers: { apikey: status.ANON_KEY } });
  if (!response.ok) throw new Error("Could not read local Auth settings");
  const settings = await response.json();
  if (settings.disable_signup !== true || settings.external?.email !== true) {
    throw new Error("E2E requires email login enabled and public signup disabled");
  }
  const admin = createClient(status.API_URL, status.SERVICE_ROLE_KEY, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
  const { data, error } = await admin.auth.admin.createUser({
    email: process.env.E2E_EMAIL!, password: process.env.E2E_PASSWORD!, email_confirm: true,
  });
  if (error || !data.user) throw new Error("Could not create disposable local E2E user");
  const userId = data.user.id;
  const cleanup = async () => {
    deleteOwnedStrategyVersions(userId);
    const { error } = await admin.auth.admin.deleteUser(userId);
    if (error) throw new Error(`Could not delete disposable local E2E user (status ${error.status}, code ${error.code})`);
  };
  try {
    // A profile may only use an alias registered to its owner, and registration
    // is an operator step with no client write path, so it runs as the admin.
    // The grant references the user, so deleting the user removes it.
    const grant = await admin.from("broker_alias_owners").insert({ alias: process.env.E2E_ALIAS!, user_id: userId });
    if (grant.error) throw new Error("Could not register the disposable E2E alias");
    // Profile insertion uses the test user's session, not service-role table access.
    const user = createClient(status.API_URL, status.ANON_KEY, { auth: { persistSession: false, autoRefreshToken: false } });
    const login = await user.auth.signInWithPassword({ email: process.env.E2E_EMAIL!, password: process.env.E2E_PASSWORD! });
    if (login.error) throw new Error(`Could not sign in disposable E2E user (status ${login.error.status}, code ${login.error.code})`);
    const profile = await user.from("broker_profiles").insert({ user_id: userId, alias: process.env.E2E_ALIAS!, mode: "demo" });
    if (profile.error) throw new Error("Could not create disposable E2E profile");
    await user.auth.signOut();
  } catch (error) {
    await cleanup();
    throw error;
  }
  return cleanup;
}
