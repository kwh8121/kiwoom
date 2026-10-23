import { createServerClient } from "@/lib/supabase/server";

// public.mfa_satisfied() is the function the row policies call: false means a
// verified factor exists and this session has not presented it. Reusing it
// keeps the screens and the data boundary from drifting apart.
export async function secondFactorPending(): Promise<boolean> {
  const supabase = await createServerClient();
  const { data, error } = await supabase.rpc("mfa_satisfied");
  // Failing open would hand out screens the policies then refuse to fill,
  // which reads as data loss rather than as a locked door.
  if (error) return true;
  return data !== true;
}
