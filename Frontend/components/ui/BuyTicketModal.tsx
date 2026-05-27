"use client";
import { useState } from "react";
import { useAuth } from "@clerk/nextjs";
import { api, setAuthToken } from "@/lib/api";
import { useRouter } from "next/navigation";
import { X } from "lucide-react";

declare global {
  interface Window { Razorpay: any; }
}

interface Props {
  listing: any;
  event:   any;
  onClose: () => void;
}

export function BuyTicketModal({ listing, event, onClose }: Props) {
  const { getToken, isSignedIn } = useAuth();
  const router  = useRouter();
  const [step, setStep] = useState<"details" | "paying" | "done">("details");
  const [qty,  setQty]  = useState(1);
  const [form, setForm] = useState({ name: "", email: "", phone: "" });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const total = (listing.price * qty).toLocaleString();

  const handleSubmit = async () => {
    if (!isSignedIn) {
      router.push("/sign-in");
      return;
    }
    if (!form.name || !form.email || !form.phone) {
      setError("All fields are required.");
      return;
    }
    setError("");
    setLoading(true);
    setStep("paying");

    try {
      const token = await getToken();
      setAuthToken(token);

      // 1. Initiate booking — locks listing + creates Razorpay order
      const { data: initData } = await api.post("/bookings/initiate", {
        listing_id:  listing.id,
        quantity:    qty,
        buyer_name:  form.name,
        buyer_email: form.email,
        buyer_phone: form.phone,
      });

      // 2. Load Razorpay script dynamically
      await loadRazorpayScript();

      // 3. Open Razorpay checkout
      const rzp = new window.Razorpay({
        key:         initData.razorpay_key_id,
        amount:      initData.amount * 100,
        currency:    "INR",
        name:        "TicketVault",
        description: `${qty}x ${event.title}`,
        order_id:    initData.razorpay_order_id,
        prefill: {
          name:    form.name,
          email:   form.email,
          contact: form.phone,
        },
        theme: { color: "#f59e0b" },

        handler: async (response: any) => {
          // 4. Verify payment on backend
          try {
            const t = await getToken();
            setAuthToken(t);
            await api.post("/bookings/verify-payment", {
              booking_id:           initData.booking_id,
              razorpay_order_id:    response.razorpay_order_id,
              razorpay_payment_id:  response.razorpay_payment_id,
              razorpay_signature:   response.razorpay_signature,
            });
            setStep("done");
            // Redirect to confirmation page after 2s
            setTimeout(() => {
              router.push(`/bookings/${initData.booking_id}/confirm`);
            }, 2000);
          } catch (e: any) {
            setError(e.message);
            setStep("details");
          }
        },

        modal: {
          ondismiss: () => {
            setStep("details");
            setLoading(false);
          },
        },
      });

      rzp.open();

    } catch (e: any) {
      setError(e.message ?? "Failed to initiate payment.");
      setStep("details");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-zinc-950/80 backdrop-blur-sm">
      <div className="relative w-full max-w-md bg-zinc-900 border border-zinc-800 rounded-2xl p-6">
        <button onClick={onClose} className="absolute top-4 right-4 text-zinc-500 hover:text-zinc-300">
          <X className="w-5 h-5" />
        </button>

        {step === "done" ? (
          <div className="text-center py-8">
            <div className="text-4xl mb-4">🎟️</div>
            <h2 className="font-display text-3xl tracking-wide text-amber-400 mb-2">PAYMENT SUCCESS</h2>
            <p className="text-zinc-400 text-sm">Redirecting to your booking...</p>
          </div>
        ) : (
          <>
            <h2 className="font-display text-3xl tracking-wide text-zinc-100 mb-1">BUY TICKET</h2>
            <p className="text-zinc-500 text-sm mb-6">{event.title}</p>

            {/* Quantity */}
            <div className="mb-4">
              <label className="block text-xs text-zinc-500 mb-1.5 tracking-wider uppercase">Quantity</label>
              <div className="flex items-center gap-3">
                <button
                  onClick={() => setQty(q => Math.max(1, q - 1))}
                  className="w-9 h-9 rounded-lg bg-zinc-800 text-zinc-300 hover:bg-zinc-700 flex items-center justify-center font-mono text-lg"
                >-</button>
                <span className="font-mono text-zinc-100 w-6 text-center">{qty}</span>
                <button
                  onClick={() => setQty(q => Math.min(listing.quantity, q + 1))}
                  className="w-9 h-9 rounded-lg bg-zinc-800 text-zinc-300 hover:bg-zinc-700 flex items-center justify-center font-mono text-lg"
                >+</button>
                <span className="text-zinc-500 text-sm ml-1">of {listing.quantity} available</span>
              </div>
            </div>

            {/* Buyer details */}
            {[
              { label: "Full Name",     key: "name",  type: "text",  placeholder: "Your name" },
              { label: "Email",         key: "email", type: "email", placeholder: "your@email.com" },
              { label: "Phone Number",  key: "phone", type: "tel",   placeholder: "+91 98765 43210" },
            ].map(({ label, key, type, placeholder }) => (
              <div key={key} className="mb-4">
                <label className="block text-xs text-zinc-500 mb-1.5 tracking-wider uppercase">{label}</label>
                <input
                  type={type}
                  value={(form as any)[key]}
                  onChange={e => setForm(f => ({ ...f, [key]: e.target.value }))}
                  placeholder={placeholder}
                  className="w-full px-4 py-2.5 rounded-lg bg-zinc-800 border border-zinc-700 text-zinc-100 text-sm focus:outline-none focus:border-zinc-500 placeholder:text-zinc-600"
                />
              </div>
            ))}

            {/* Total */}
            <div className="flex items-center justify-between px-4 py-3 rounded-lg bg-zinc-950 border border-zinc-800 mb-4">
              <span className="text-zinc-500 text-sm">Total ({qty} ticket{qty > 1 ? "s" : ""})</span>
              <span className="text-amber-400 font-mono font-medium text-lg">₹{total}</span>
            </div>

            {error && (
              <p className="text-red-400 text-sm bg-red-400/10 border border-red-400/20 px-4 py-2 rounded-lg mb-4">
                {error}
              </p>
            )}

            <button
              onClick={handleSubmit}
              disabled={loading || step === "paying"}
              className="w-full py-3 rounded-lg bg-amber-500 text-zinc-950 font-medium hover:bg-amber-400 transition-colors disabled:opacity-50"
            >
              {loading ? "Processing..." : `Pay ₹${total} via Razorpay`}
            </button>

            <p className="text-zinc-600 text-xs text-center mt-3">
              Secured by Razorpay · Ticket locked for 5 minutes during payment
            </p>
          </>
        )}
      </div>
    </div>
  );
}

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
