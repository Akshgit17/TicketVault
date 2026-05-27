import axios, { AxiosError } from "axios";

export const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000",
  timeout: 60000, // Increased timeout to 60s
});

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
      console.warn("[api] 401 — token may be expired");
    }
    return Promise.reject(new Error(detail ?? err.message ?? "Unknown error"));
  }
);
