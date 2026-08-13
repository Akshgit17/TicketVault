import axios, { AxiosError } from "axios";

export const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000",
  timeout: 60000,
});

/**
 * Supplies a fresh Clerk token. Registered once by TokenSync in providers.tsx.
 *
 * Held in a module variable rather than passed around because axios
 * interceptors run outside React and cannot call hooks.
 */
type TokenGetter = () => Promise<string | null>;
let getFreshToken: TokenGetter | null = null;

export function registerTokenGetter(fn: TokenGetter | null) {
  getFreshToken = fn;
}

/**
 * Attach a CURRENT token to every authenticated request.
 *
 * This replaced a pattern where each page called `setAuthToken(await
 * getToken())` before its own requests. That worked for as long as you
 * remembered it, and Clerk session tokens expire after about 60 seconds, so
 * any component that forgot would work in testing and fail in use. Three
 * extracted dialogs did forget, and cancelling a concert failed with
 * "Authentication failed" for anyone who had the page open for a minute.
 *
 * Asking Clerk per request is cheap: getToken() returns its cached token and
 * only performs a network refresh when the current one is near expiry.
 */
api.interceptors.request.use(async (config) => {
  if (!getFreshToken) return config;
  try {
    const token = await getFreshToken();
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
  } catch {
    // Signed out, or Clerk is unreachable. Send the request without a token
    // and let the backend answer with a 401, rather than failing here and
    // breaking the public endpoints that need no auth at all.
  }
  return config;
});

/**
 * Kept for the sign-in path, which sets a token before the getter exists.
 * Ordinary requests no longer need it.
 */
export function setAuthToken(token: string | null) {
  if (token) {
    api.defaults.headers.common["Authorization"] = `Bearer ${token}`;
  } else {
    delete api.defaults.headers.common["Authorization"];
  }
}

api.interceptors.response.use(
  (res) => res,
  (err: AxiosError<{ detail: any }>) => {
    let detail = err.response?.data?.detail;
    if (Array.isArray(detail)) {
      detail = detail.map((d: any) => `${d.loc.join(".")}: ${d.msg}`).join(", ");
    }
    if (err.response?.status === 401) {
      console.warn("[api] 401, token may be expired");
    }
    return Promise.reject(new Error(detail ?? err.message ?? "Unknown error"));
  }
);
