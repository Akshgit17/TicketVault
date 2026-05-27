"use client";
import { useEffect, useState } from "react";
import { useAuth } from "@clerk/nextjs";
import { api, setAuthToken } from "@/lib/api";
import { CountdownTimer } from "@/components/ui/CountdownTimer";
import { useRouter } from "next/navigation";
import { Calendar, MapPin } from "lucide-react";

export default function BookingConfirmPage({ params }: { params: { id: string } }) {
  const { getToken } = useAuth();
  const router = useRouter();
  const [booking, setBooking] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [acting, setActing]   = useState(false);
  const [error, setError]     = useState("");
  const [done, setDone]       = useState("");

  useEffect(() => {
    (async () => {
      const token = await getToken();
      setAuthToken(token);
      try {
        const { data } = await api.get(`/bookings/${params.id}`);
        setBooking(data);
      } catch (e: any) {
        setError(e.message);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const act = async (action: "confirm" | "dispute") => {
    setActing(true);
    setError("");
    try {
      const token = await getToken();
      setAuthToken(token);
      if (action === "confirm") {
        await api.post("/bookings/confirm", { booking_id: params.id });
        setDone("confirmed");
      } else {
        await api.post("/bookings/dispute", { booking_id: params.id, reason: "Issue reported by buyer" });
        setDone("disputed");
      }
    } catch (e: any) {
      setError(e.message);
    } finally {
      setActing(false);
    }
  };

  if (loading) return (
    <div className="flex items-center justify-center min-h-[60vh]">
      <div className="w-8 h-8 border-2 border-amber-400 border-t-transparent rounded-full animate-spin" />
    </div>
  );

  if (error && !booking) return (
    <div className="max-w-lg mx-auto px-4 py-16 text-red-400">{error}</div>
  );

  const listing = booking?.listings;
  const event   = listing?.events;
  const date    = event ? new Date(event.date).toLocaleDateString("en-IN", {
    weekday: "short", day: "numeric", month: "short", year: "numeric",
  }) : "";
  const qrUrl =
    booking?.qr_signed_url
    || (booking?.listings?.qr_image_url
      ? `${process.env.NEXT_PUBLIC_SUPABASE_URL}/storage/v1/object/public/ticket-qrs/${booking.listings.qr_image_url}`
      : null);

  if (done) return (
    <div className="max-w-lg mx-auto px-4 py-16 text-center">
      <div className="text-6xl mb-4">{done === "confirmed" ? "✅" : "🚨"}</div>
      <h1 className="font-display text-4xl tracking-wide text-zinc-100 mb-2">
        {done === "confirmed" ? "TICKET CONFIRMED" : "DISPUTE FILED"}
      </h1>
      <p className="text-zinc-400 text-sm mb-6">
        {done === "confirmed"
          ? "Your ticket has been confirmed. Enjoy the show!"
          : "Your dispute has been filed. Our team will review it."}
      </p>
      <button onClick={() => router.push("/dashboard")}
        className="px-6 py-2.5 rounded-lg bg-zinc-800 text-zinc-300 hover:bg-zinc-700 transition-colors text-sm">
        Go to Dashboard
      </button>
    </div>
  );

  return (
    <div className="max-w-lg mx-auto px-4 py-16">
      <h1 className="font-display text-5xl tracking-wide text-zinc-100 mb-2">CONFIRM TICKET</h1>
      <p className="text-zinc-500 text-sm mb-8">Verify your ticket details and confirm receipt within 2 hours.</p>

      {/* Event info */}
      {event && (
        <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-5 mb-6 space-y-2">
          <p className="font-display text-2xl tracking-wide">{event.title}</p>
          <div className="flex gap-4 text-zinc-500 text-sm">
            <span className="flex items-center gap-1"><Calendar className="w-3.5 h-3.5" />{date}</span>
            <span className="flex items-center gap-1"><MapPin className="w-3.5 h-3.5" />{event.venue}</span>
          </div>
          <div className="flex justify-between pt-2 border-t border-zinc-800">
            <span className="text-zinc-500 text-sm">Qty: {booking.quantity}</span>
            <span className="text-amber-400 font-mono">₹{booking.total_price?.toLocaleString()}</span>
          </div>
        </div>
      )}

      {/* QR Code */}
      {qrUrl && (
        <div className="mb-6">
          <p className="text-xs text-zinc-500 mb-2 tracking-wider uppercase">Your QR Code</p>
          <img
            src={qrUrl}
            alt="QR Code"
            className="w-48 h-48 rounded-xl border border-zinc-700 bg-zinc-800"
          />
        </div>
      )}

      {!qrUrl && booking?.payment_status === "paid" && (
        <div className="mb-6 px-4 py-3 rounded-lg bg-zinc-800 border border-zinc-700 text-zinc-500 text-sm">
          QR code not provided by seller. You can dispute this purchase.
        </div>
      )}

      {/* Countdown */}
      {booking?.confirmation_deadline && booking?.confirmation_status === "pending" && (
        <div className="mb-8">
          <p className="text-xs text-zinc-500 mb-3 tracking-wider uppercase">Time remaining to confirm</p>
          <CountdownTimer deadline={booking.confirmation_deadline} />
        </div>
      )}

      {booking?.confirmation_status !== "pending" && (
        <div className="mb-6 px-4 py-3 rounded-lg bg-zinc-900 border border-zinc-700 text-zinc-400 text-sm">
          Status: <span className="text-amber-400 capitalize">{booking?.confirmation_status?.replace("_", " ")}</span>
        </div>
      )}

      {error && (
        <p className="text-red-400 text-sm bg-red-400/10 border border-red-400/20 px-4 py-2 rounded-lg mb-4">
          {error}
        </p>
      )}

      {booking?.confirmation_status === "pending" && (
        <div className="flex gap-3">
          <button
            onClick={() => act("confirm")}
            disabled={acting}
            className="flex-1 py-3 rounded-lg bg-amber-500 text-zinc-950 font-medium hover:bg-amber-400 transition-colors disabled:opacity-50"
          >
            ✓ Confirm Received
          </button>
          <button
            onClick={() => act("dispute")}
            disabled={acting}
            className="flex-1 py-3 rounded-lg border border-red-500/50 text-red-400 hover:bg-red-500/10 transition-colors disabled:opacity-50"
          >
            ✗ Report Issue
          </button>
        </div>
      )}
    </div>
  );
}
