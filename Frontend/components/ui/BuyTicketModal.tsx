"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth, useUser } from "@clerk/nextjs";
import { toast } from "sonner";
import { Lock, ShieldCheck } from "lucide-react";

import { api, setAuthToken } from "@/lib/api";
import { useConfig } from "@/lib/config";
import { inr } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter,
  DialogHeader, DialogTitle,
} from "@/components/ui/dialog";

declare global {
  interface Window { Razorpay: any; }
}

export function BuyTicketModal({
  listing,
  event,
  onClose,
}: {
  listing: any;
  event: any;
  onClose: () => void;
}) {
  const { getToken, isSignedIn } = useAuth();
  const { user } = useUser();
  const { config } = useConfig();
  const router = useRouter();

  const [form, setForm] = useState({ name: "", email: "", phone: "" });
  const [loading, setLoading] = useState(false);

  // Prefill from Clerk. Asking a signed-in user to retype their own name and
  // email is friction with no purpose — they already gave it to us.
  useEffect(() => {
    if (!user) return;
    setForm((f) => ({
      name: f.name || user.fullName || "",
      email: f.email || user.primaryEmailAddress?.emailAddress || "",
      phone: f.phone || user.primaryPhoneNumber?.phoneNumber || "",
    }));
  }, [user]);

  const total = Number(listing.price);
  const compensation = total * config.buyer_compensation_rate;
  const valid = form.name.trim() && form.email.trim() && form.phone.replace(/\D/g, "").length >= 10;

  function loadRazorpay(): Promise<void> {
    return new Promise((resolve, reject) => {
      if (window.Razorpay) return resolve();
      const s = document.createElement("script");
      s.src = "https://checkout.razorpay.com/v1/checkout.js";
      s.onload = () => resolve();
      s.onerror = () => reject(new Error("Could not load the payment window."));
      document.body.appendChild(s);
    });
  }

  const submit = async () => {
    if (!isSignedIn) return router.push("/sign-in");
    if (!valid) return;

    setLoading(true);
    try {
      setAuthToken(await getToken());

      const { data: init } = await api.post("/bookings/initiate", {
        listing_id: listing.id,
        quantity: 1,
        buyer_name: form.name.trim(),
        buyer_email: form.email.trim(),
        buyer_phone: form.phone.trim(),
      });

      await loadRazorpay();

      const rzp = new window.Razorpay({
        key: init.razorpay_key_id,
        amount: Math.round(init.amount * 100),
        currency: "INR",
        name: "TicketVault",
        description: event.title ?? "Concert ticket",
        order_id: init.razorpay_order_id,
        prefill: { name: form.name, email: form.email, contact: form.phone },
        theme: { color: "#f59e0b" },
        handler: async (res: any) => {
          try {
            setAuthToken(await getToken());
            await api.post("/bookings/verify-payment", {
              booking_id: init.booking_id,
              razorpay_order_id: res.razorpay_order_id,
              razorpay_payment_id: res.razorpay_payment_id,
              razorpay_signature: res.razorpay_signature,
            });
            toast.success("Payment held in escrow", {
              description: "Next: share the number your ticketing account uses.",
            });
            // Navigate immediately. The old flow used a 2s setTimeout, which
            // left the user staring at a modal wondering if it had worked.
            router.push(`/bookings/${init.booking_id}/confirm`);
          } catch (e: any) {
            toast.error("We couldn't confirm that payment", { description: e.message });
          }
        },
        modal: {
          ondismiss: () => setLoading(false),
        },
      });

      rzp.open();
    } catch (e: any) {
      toast.error("Couldn't start checkout", { description: e.message });
      setLoading(false);
    }
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>CHECKOUT</DialogTitle>
          <DialogDescription>{event.title}</DialogDescription>
        </DialogHeader>

        <div className="space-y-5 p-5">
          <div className="rounded-lg border border-border bg-secondary/30 p-4">
            <div className="flex items-baseline justify-between">
              <span className="text-sm text-muted-foreground">You pay</span>
              <span className="tnum font-mono text-2xl text-primary">{inr(total)}</span>
            </div>
            <div className="perforation my-3" />
            <p className="flex items-start gap-2 text-xs text-muted-foreground">
              <ShieldCheck className="mt-0.5 size-3.5 shrink-0 text-primary" />
              Held by TicketVault until the ticket is in your account. If the
              seller doesn&apos;t deliver within {config.transfer_sla_hours} hours,
              you get a full refund plus {inr(compensation)}.
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="buy-name">Full name</Label>
            <Input
              id="buy-name" value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="buy-email">Email</Label>
            <Input
              id="buy-email" type="email" value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="buy-phone">Phone</Label>
            <Input
              id="buy-phone" type="tel" inputMode="numeric" value={form.phone}
              onChange={(e) => setForm({ ...form, phone: e.target.value })}
              className="tnum font-mono"
            />
            <p className="text-xs text-muted-foreground">
              For order updates. You&apos;ll confirm your ticketing-app number
              separately, after payment.
            </p>
          </div>
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button disabled={!valid} loading={loading} onClick={submit}>
            <Lock />
            Pay {inr(total)}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
