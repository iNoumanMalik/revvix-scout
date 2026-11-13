import { createClient, type Session } from "@supabase/supabase-js";

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL?.trim();
const publishableKey = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY?.trim();
const authMode = import.meta.env.VITE_SCOUT_AUTH_MODE?.trim();

export const browserAuthConfigured = authMode === "supabase" && import.meta.env.MODE !== "test";

const supabase =
  browserAuthConfigured && supabaseUrl && publishableKey
    ? createClient(supabaseUrl, publishableKey, {
        auth: {
          persistSession: true,
          autoRefreshToken: true,
          detectSessionInUrl: true,
        },
      })
    : null;

export async function accessToken(): Promise<string | null> {
  if (!supabase) return null;
  const { data, error } = await supabase.auth.getSession();
  if (error) throw error;
  return data.session?.access_token ?? null;
}

export async function signIn(email: string, password: string): Promise<void> {
  if (!supabase) throw new Error("Supabase browser authentication is not configured.");
  const { error } = await supabase.auth.signInWithPassword({ email, password });
  if (error) throw error;
}

export async function signOut(): Promise<void> {
  if (!supabase) return;
  const { error } = await supabase.auth.signOut();
  if (error) throw error;
}

export function observeBrowserSession(listener: (session: Session | null) => void): () => void {
  if (!supabase) {
    listener(null);
    return () => undefined;
  }
  void supabase.auth.getSession().then(({ data }) => listener(data.session));
  const { data } = supabase.auth.onAuthStateChange((_event, session) => listener(session));
  return () => data.subscription.unsubscribe();
}
