"use client";
import { ClerkProvider, useAuth, useUser } from "@clerk/nextjs";
import { useEffect } from "react";
import { setAuthToken, api } from "@/lib/api";

function TokenSync() {
  const { getToken, isLoaded, isSignedIn } = useAuth();
  const { user } = useUser();

  useEffect(() => {
    if (!isLoaded || !isSignedIn || !user) return;

    const sync = async () => {
      const token = await getToken();
      if (!token) return;

      setAuthToken(token);

      // Resolve the best available name
      const name =
        user.fullName ||
        `${user.firstName ?? ""} ${user.lastName ?? ""}`.trim() ||
        user.username ||
        user.primaryEmailAddress?.emailAddress?.split("@")[0] ||
        "Anonymous";

      const email = user.primaryEmailAddress?.emailAddress;
      if (!email) {
        console.warn("[TokenSync] No email found on Clerk user — skipping sync");
        return;
      }

      try {
        const res = await api.post("/users/me", { name, email });
        console.log("[TokenSync] User synced to Supabase:", res.data);
      } catch (err: any) {
        console.error("[TokenSync] Failed to sync user:", err?.message ?? err);
      }
    };

    sync();
  }, [getToken, isLoaded, isSignedIn, user]);

  return null;
}

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <ClerkProvider>
      <TokenSync />
      {children}
    </ClerkProvider>
  );
}
