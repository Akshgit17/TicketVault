"use client";

import { ClerkProvider, useAuth, useUser } from "@clerk/nextjs";
import { useEffect } from "react";
import { toast } from "sonner";
import { registerTokenGetter, setAuthToken, api } from "@/lib/api";
import { ConfigProvider } from "@/lib/config";
import { Toaster } from "@/components/ui/toaster";

function TokenSync() {
  const { getToken, isLoaded, isSignedIn } = useAuth();
  const { user } = useUser();

  // Hand Clerk's getToken to the axios layer so every request attaches a
  // CURRENT token. Registered as soon as Clerk loads, before any component
  // gets a chance to call the API, and cleared on sign-out so a stale getter
  // cannot keep authenticating requests.
  useEffect(() => {
    if (!isLoaded) return;
    registerTokenGetter(isSignedIn ? () => getToken() : null);
    if (!isSignedIn) setAuthToken(null);
    return () => registerTokenGetter(null);
  }, [getToken, isLoaded, isSignedIn]);

  useEffect(() => {
    if (!isLoaded || !isSignedIn || !user) return;

    const sync = async () => {
      const token = await getToken();
      if (!token) return;

      setAuthToken(token);

      // Identity is derived server-side from the verified Clerk token — the
      // client no longer sends name/email, since it cannot be trusted for them.
      try {
        await api.post("/users/me");
      } catch (err: any) {
        // Fail loudly. This used to be a bare console.error, so a broken sync
        // was invisible until the user hit checkout and got "User not found in
        // Supabase" — an error five steps removed from its cause, and phrased
        // for whoever wrote it rather than whoever reads it.
        const detail = String(err?.message ?? err);
        console.error("[TokenSync] Failed to sync user:", detail);

        toast.error("We couldn't finish signing you in", {
          description: detail.includes("email claim")
            ? "Your account is missing an email claim. Add `email` to the Clerk session token, then sign out and back in."
            : "Some actions won't work until this resolves. Try signing out and back in.",
          duration: 10000,
        });
      }
    };

    sync();
  }, [getToken, isLoaded, isSignedIn, user]);

  return null;
}

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <ClerkProvider>
      <ConfigProvider>
        <TokenSync />
        {children}
        <Toaster />
      </ConfigProvider>
    </ClerkProvider>
  );
}
