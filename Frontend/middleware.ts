import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server";

const isProtected = createRouteMatcher([
  "/sell(.*)",
  "/dashboard(.*)",
  "/bookings(.*)",
  // Sign-in gate only. Whether the user is actually an admin is decided by the
  // backend on every /admin/* API call — middleware cannot see the is_admin
  // flag, which lives in the database rather than in the Clerk token.
  "/admin(.*)",
]);

export default clerkMiddleware((auth, req) => {
  if (isProtected(req)) auth().protect();
});

export const config = {
  matcher: ["/((?!_next|.*\\..*).*)"],
};
