"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@clerk/nextjs";
import { api } from "@/lib/api";

export interface Me {
  id: string;
  name: string;
  email: string;
  is_admin?: boolean;
}

/**
 * The signed-in user's *database* row, which is where `is_admin` lives.
 *
 * Clerk knows who you are; only the backend knows what you're allowed to do.
 * The admin nav link is driven from this — and it is a convenience only, since
 * every /admin route re-checks the flag server-side.
 */
export function useMe() {
  const { isLoaded, isSignedIn } = useAuth();
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!isLoaded) return;
    if (!isSignedIn) {
      setMe(null);
      setLoading(false);
      return;
    }

    let cancelled = false;
    // TokenSync sets the auth header on the shared axios instance; give it a
    // tick to land before the first authenticated call.
    const t = setTimeout(() => {
      api
        .get("/users/me")
        .then(({ data }) => {
          if (!cancelled) setMe(data);
        })
        .catch(() => {
          if (!cancelled) setMe(null);
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }, 150);

    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [isLoaded, isSignedIn]);

  return { me, loading, isSignedIn: isLoaded && isSignedIn };
}
