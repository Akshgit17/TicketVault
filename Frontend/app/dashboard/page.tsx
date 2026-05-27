"use client";
import { useEffect, useState } from "react";
import { useAuth } from "@clerk/nextjs";
import { api, setAuthToken } from "@/lib/api";
import Link from "next/link";
import clsx from "clsx";

const LISTING_STATUS_COLOR: Record<string, string> = {
  pending_fee: "text-amber-400 bg-amber-400/10",
  active:    "text-emerald-400 bg-emerald-400/10",
  locked:    "text-yellow-400 bg-yellow-400/10",
  sold:      "text-zinc-400 bg-zinc-400/10",
  cancelled: "text-red-400 bg-red-400/10",
};

const BOOKING_STATUS_COLOR: Record<string, string> = {
  pending:        "text-yellow-400 bg-yellow-400/10",
  paid:           "text-emerald-400 bg-emerald-400/10",
  failed:         "text-red-400 bg-red-400/10",
  confirmed:      "text-teal-400 bg-teal-400/10",
  auto_confirmed: "text-teal-400 bg-teal-400/10",
  disputed:       "text-orange-400 bg-orange-400/10",
};

export default function DashboardPage() {
  const { getToken } = useAuth();
  const [listings, setListings] = useState<any[]>([]);
  const [bookings, setBookings] = useState<any[]>([]);
  const [loading, setLoading]   = useState(true);
  const [tab, setTab]           = useState<"buying" | "selling">("buying");

  useEffect(() => {
    (async () => {
      const token = await getToken();
      setAuthToken(token);
      try {
        // User sync is handled by TokenSync in providers.tsx
        const [listRes, bookRes] = await Promise.all([
          api.get("/listings/my/all"),
          api.get("/bookings/my/all"),
        ]);
        setListings(listRes.data);
        setBookings(bookRes.data);
      } catch (e) {
        console.error(e);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const handleUnlist = async (listingId: string) => {
    if (!confirm("Are you sure you want to unlist this ticket?")) return;
    try {
      const token = await getToken();
      setAuthToken(token);
      await api.post(`/listings/${listingId}/unlist`);
      // Refresh listings
      const { data } = await api.get("/listings/my/all");
      setListings(data);
    } catch (e: any) {
      alert(e.message ?? "Failed to unlist.");
    }
  };

  const handlePayFee = async (listingId: string) => {
    try {
      const token = await getToken();
      setAuthToken(token);
      
      const { data: feeData } = await api.post(`/listings/${listingId}/initiate-fee`);
      
      const rzp = new window.Razorpay({
        key:         feeData.razorpay_key_id,
        amount:      feeData.amount * 100,
        order_id:    feeData.razorpay_order_id,
        name:        "TicketVault",
        description: "Listing Fee Payment",
        theme: { color: "#f59e0b" },
        handler: async (res: any) => {
          await api.post(`/listings/${listingId}/verify-fee`, {
            razorpay_order_id:   res.razorpay_order_id,
            razorpay_payment_id: res.razorpay_payment_id,
            razorpay_signature:  res.razorpay_signature,
          });
          window.location.reload();
        }
      });
      rzp.open();
    } catch (e: any) {
      alert(e.message ?? "Payment failed.");
    }
  };

  return (
    <div className="max-w-5xl mx-auto px-4 py-12">
      <h1 className="font-display text-5xl tracking-wide text-zinc-100 mb-8">DASHBOARD</h1>

      {/* Tabs */}
      <div className="flex gap-1 mb-8 bg-zinc-900 border border-zinc-800 rounded-lg p-1 w-fit">
        {(["buying", "selling"] as const).map(t => (
          <button key={t} onClick={() => setTab(t)}
            className={clsx(
              "px-5 py-2 rounded-md text-sm font-medium transition-colors capitalize",
              tab === t ? "bg-zinc-700 text-zinc-100" : "text-zinc-500 hover:text-zinc-300"
            )}>
            {t === "buying" ? `My Purchases (${bookings.length})` : `My Listings (${listings.length})`}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="space-y-2">
          {Array(3).fill(0).map((_, i) => <div key={i} className="h-16 rounded-lg bg-zinc-800 animate-pulse" />)}
        </div>
      ) : tab === "buying" ? (
        /* ── BOOKINGS ── */
        bookings.length === 0 ? (
          <div className="text-center py-12 border border-zinc-800 rounded-xl text-zinc-600">
            <p className="font-display text-2xl tracking-wide">NO PURCHASES YET</p>
            <Link href="/marketplace" className="text-amber-400 text-sm mt-2 block hover:text-amber-300">
              Browse tickets →
            </Link>
          </div>
        ) : (
          <div className="space-y-2">
            {bookings.map((b) => {
              const confStatus = b.confirmation_status ?? b.payment_status;
              return (
                <div key={b.id} className="flex items-center justify-between px-4 py-3 rounded-lg bg-zinc-900 border border-zinc-800">
                  <div>
                    <p className="text-zinc-200 text-sm font-medium">
                      {b.listings?.events?.title ?? b.listings?.events?.name ?? "Untitled Event"}
                    </p>
                    <p className="text-zinc-600 text-xs">{b.listings?.cities?.name} · Qty: {b.quantity}</p>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="font-mono text-amber-400 text-sm">₹{b.total_price?.toLocaleString()}</span>
                    <span className={clsx("text-xs px-2 py-0.5 rounded-full",
                      BOOKING_STATUS_COLOR[confStatus] ?? BOOKING_STATUS_COLOR[b.payment_status] ?? "text-zinc-400")}>
                      {confStatus?.replace(/_/g, " ")}
                    </span>
                    {b.payment_status === "paid" && b.confirmation_status === "pending" && (
                      <Link href={`/bookings/${b.id}/confirm`}
                        className="text-xs px-3 py-1 rounded-lg bg-amber-500 text-zinc-950 font-medium hover:bg-amber-400 transition-colors">
                        Confirm
                      </Link>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )
      ) : (
        /* ── LISTINGS ── */
        <div>
          <div className="flex justify-end mb-4">
            <Link href="/sell" className="text-xs text-amber-400 hover:text-amber-300 transition-colors">
              + New listing
            </Link>
          </div>
          {listings.length === 0 ? (
            <div className="text-center py-12 border border-zinc-800 rounded-xl text-zinc-600">
              <p className="font-display text-2xl tracking-wide">NO LISTINGS YET</p>
              <Link href="/sell" className="text-amber-400 text-sm mt-2 block hover:text-amber-300">
                Create your first listing →
              </Link>
            </div>
          ) : (
            <div className="space-y-2">
              {listings.map((l) => (
                <div key={l.id} className="flex items-center justify-between px-4 py-3 rounded-lg bg-zinc-900 border border-zinc-800">
                  <div>
                    <p className="text-zinc-200 text-sm font-medium">
                      {l.events?.title ?? l.events?.name ?? "Untitled Event"}
                    </p>
                    <p className="text-zinc-600 text-xs">{l.cities?.name} · Qty: {l.quantity}</p>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="font-mono text-amber-400 text-sm">₹{l.price?.toLocaleString()}</span>
                    <span className={clsx("text-xs px-2 py-0.5 rounded-full capitalize",
                      LISTING_STATUS_COLOR[l.status] ?? "text-zinc-400")}>
                      {l.status.replace(/_/g, " ")}
                    </span>
                    
                    {l.status === "pending_fee" && (
                      <button onClick={() => handlePayFee(l.id)}
                        className="text-[10px] px-2 py-0.5 rounded bg-amber-500 text-zinc-950 font-bold hover:bg-amber-400 transition-colors">
                        PAY FEE
                      </button>
                    )}

                    {(l.status === "active" || l.status === "pending_fee") && (
                      <button onClick={() => handleUnlist(l.id)}
                        className="text-[10px] px-2 py-0.5 rounded bg-zinc-800 text-zinc-400 hover:text-red-400 transition-colors">
                        UNLIST
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
