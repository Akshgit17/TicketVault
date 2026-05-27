"use client";
import { useState, useEffect } from "react";
import { useAuth } from "@clerk/nextjs";
import { api, setAuthToken } from "@/lib/api";
import { useCityStore } from "@/store/city";
import { QRUpload } from "@/components/ui/QRUpload";
import { useRouter } from "next/navigation";

declare global {
  interface Window { Razorpay: any; }
}

export default function SellPage() {
  const { getToken } = useAuth();
  const { selectedCity } = useCityStore();
  const router = useRouter();

  const [cities, setCities]     = useState<any[]>([]);
  const [events, setEvents]     = useState<any[]>([]);
  const [cityId, setCityId]     = useState("");
  const [eventId, setEventId]   = useState("");
  const [price, setPrice]       = useState("");
  const [origPrice, setOrigPrice] = useState("");
  const [quantity, setQuantity] = useState("1");
  const [qrFile, setQrFile]     = useState<File[]>([]);
  const [error, setError]       = useState("");
  const [loading, setLoading]   = useState(false);
  const [success, setSuccess]   = useState(false);

  const listingFee = price ? (parseFloat(price) * 0.2).toFixed(2) : "0.00";

  // Load cities on mount
  useEffect(() => {
    api.get("/cities").then(({ data }) => setCities(data));
  }, []);

  // Pre-select city from navbar selection
  useEffect(() => {
    if (!selectedCity || cities.length === 0) return;
    const found = cities.find((c: any) => c.name === selectedCity);
    if (found) setCityId(found.id);
  }, [selectedCity, cities]);

  // Load events when city changes
  useEffect(() => {
    if (!cityId) { setEvents([]); setEventId(""); return; }
    api.get("/events", { params: { city_id: cityId } }).then(({ data }) => {
      setEvents(data);
      setEventId("");
    });
  }, [cityId]);

  const handleSubmit = async () => {
    setError("");
    if (!cityId)    return setError("Select a city.");
    if (!eventId)   return setError("Select an event.");
    if (!price)     return setError("Enter selling price.");
    if (!origPrice) return setError("Enter original price.");
    if (parseInt(quantity) < 1) return setError("Quantity must be at least 1.");
    if (!qrFile[0])   return setError("QR code is required to create a listing.");

    setLoading(true);
    try {
      const token = await getToken();
      setAuthToken(token);

      const form = new FormData();
      form.append("event_id",       eventId);
      form.append("city_id",        cityId);
      form.append("price",          price);
      form.append("original_price", origPrice);
      form.append("quantity",       quantity);
      form.append("qr_file", qrFile[0]);

      const { data: listData } = await api.post("/listings/create", form);
      const listingId = listData.listing_id;

      // 2. Initiate fee payment
      const { data: feeData } = await api.post(`/listings/${listingId}/initiate-fee`);

      // 3. Load Razorpay and open modal
      await loadRazorpayScript();

      const rzp = new window.Razorpay({
        key:         feeData.razorpay_key_id,
        amount:      Math.round(feeData.amount * 100),
        currency:    "INR",
        name:        "TicketVault",
        description: "20% Listing Fee (Refundable)",
        order_id:    feeData.razorpay_order_id,
        theme: { color: "#f59e0b" },

        handler: async (response: any) => {
          try {
            const t = await getToken();
            setAuthToken(t);
            await api.post(`/listings/${listingId}/verify-fee`, {
              razorpay_order_id:   response.razorpay_order_id,
              razorpay_payment_id: response.razorpay_payment_id,
              razorpay_signature:  response.razorpay_signature,
            });
            setSuccess(true);
            setTimeout(() => router.push("/dashboard"), 2000);
          } catch (e: any) {
            setError(e.message ?? "Fee verification failed.");
          }
        },
        modal: {
          ondismiss: () => {
            setLoading(false);
            setError("Listing created but fee not paid. Complete payment from dashboard.");
            router.push("/dashboard");
          },
        },
      });

      rzp.open();
    } catch (e: any) {
      console.error("Error creating listing:", e);
      setError(e.message ?? "Failed to create listing.");
    } finally {
      setLoading(false);
    }
  };

  function loadRazorpayScript(): Promise<void> {
    return new Promise((resolve, reject) => {
      if (window.Razorpay) { resolve(); return; }
      const script = document.createElement("script");
      script.src = "https://checkout.razorpay.com/v1/checkout.js";
      script.onload  = () => resolve();
      script.onerror = () => reject(new Error("Failed to load Razorpay script"));
      document.body.appendChild(script);
    });
  }

  if (success) return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] text-center gap-4">
      <div className="text-5xl">🎟️</div>
      <h2 className="font-display text-4xl tracking-wide text-amber-400">LISTING CREATED</h2>
      <p className="text-zinc-400 text-sm">Redirecting to dashboard...</p>
    </div>
  );

  return (
    <div className="max-w-2xl mx-auto px-4 py-12">
      <h1 className="font-display text-4xl tracking-wide text-zinc-100 mb-2 uppercase">SELL A TICKET</h1>
      <p className="text-zinc-500 text-sm mb-8">List your ticket on TicketVault marketplace.</p>

      <div className="space-y-5">
        {/* City selector */}
        <div>
          <label className="block text-xs text-zinc-500 mb-1.5 tracking-wider uppercase">City</label>
          <select
            value={cityId}
            onChange={e => setCityId(e.target.value)}
            className="w-full px-4 py-2.5 rounded-lg bg-zinc-800 border border-zinc-700 text-zinc-300 text-sm focus:outline-none focus:border-zinc-500"
          >
            <option value="">Select city</option>
            {cities.map((c: any) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </div>

        {/* Event selector */}
        <div>
          <label className="block text-xs text-zinc-500 mb-1.5 tracking-wider uppercase">Event</label>
          <select
            value={eventId}
            onChange={e => setEventId(e.target.value)}
            disabled={!cityId || events.length === 0}
            className="w-full px-4 py-2.5 rounded-lg bg-zinc-800 border border-zinc-700 text-zinc-300 text-sm focus:outline-none focus:border-zinc-500 disabled:opacity-50"
          >
            <option value="">
              {!cityId ? "Select city first" : events.length === 0 ? "No events in this city" : "Select event"}
            </option>
            {events.map((ev: any) => {
              const d = new Date(ev.date).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
              const eventLabel = ev.title ?? ev.name ?? "Untitled Event";
              return <option key={ev.id} value={ev.id}>{eventLabel} — {d}</option>;
            })}
          </select>
        </div>

        {/* Prices */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-xs text-zinc-500 mb-1.5 tracking-wider uppercase">Original Price (₹)</label>
            <input type="number" value={origPrice} onChange={e => setOrigPrice(e.target.value)}
              className="w-full px-4 py-2.5 rounded-lg bg-zinc-800 border border-zinc-700 text-zinc-100 font-mono text-sm focus:outline-none focus:border-zinc-500 [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
              placeholder="0" min="1" />
          </div>
          <div>
            <label className="block text-xs text-zinc-500 mb-1.5 tracking-wider uppercase">Selling Price (₹)</label>
            <input type="number" value={price} onChange={e => setPrice(e.target.value)}
              className="w-full px-4 py-2.5 rounded-lg bg-zinc-800 border border-zinc-700 text-zinc-100 font-mono text-sm focus:outline-none focus:border-zinc-500 [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
              placeholder="0" min="1" />
          </div>
        </div>


        {/* Listing fee */}
        {price && (
          <div className="flex flex-col gap-1 px-4 py-3 rounded-lg bg-zinc-900 border border-zinc-800 text-sm">
            <div className="flex items-center justify-between">
              <span className="text-zinc-500">Upfront Listing Fee (20%)</span>
              <span className="text-amber-400 font-mono">₹{listingFee}</span>
            </div>
            <p className="text-[10px] text-zinc-600 leading-tight italic">
              * This fee is required to activate your listing and will be **fully refunded** to you after the ticket is successfully transferred to the buyer.
            </p>
          </div>
        )}

        {/* QR Upload (required) */}
        <div>
          <label className="block text-xs text-zinc-500 mb-1.5 tracking-wider uppercase">QR Code (Required)</label>
          <QRUpload count={1} onChange={setQrFile} />
        </div>

        {error && (
          <p className="text-red-400 text-sm bg-red-400/10 border border-red-400/20 px-4 py-2 rounded-lg">
            {error}
          </p>
        )}

        <button
          onClick={handleSubmit}
          disabled={loading}
          className="w-full py-3 rounded-lg bg-amber-500 text-zinc-950 font-medium hover:bg-amber-400 transition-colors disabled:opacity-50"
        >
          {loading ? "Submitting..." : "List Ticket"}
        </button>
      </div>
    </div>
  );
}
