"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@clerk/nextjs";
import { toast } from "sonner";
import { AlertTriangle, CheckCircle2, Info, ShieldCheck } from "lucide-react";

import { api, setAuthToken } from "@/lib/api";
import { useCityStore } from "@/store/city";
import { useConfig } from "@/lib/config";
import { inr } from "@/lib/utils";
import { QRUpload } from "@/components/ui/QRUpload";
import { RequestEventDialog } from "@/components/ui/RequestEventDialog";
import { PriceGuidance, type Suggestion } from "@/components/ui/PriceGuidance";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";

declare global {
  interface Window { Razorpay: any; }
}

interface Option { id: string; name?: string; title?: string; date?: string }

export default function SellPage() {
  const { getToken } = useAuth();
  const { selected } = useCityStore();
  const { config } = useConfig();
  const router = useRouter();

  const [cities, setCities] = useState<Option[]>([]);
  const [events, setEvents] = useState<Option[]>([]);
  const [cityId, setCityId] = useState("");
  const [eventId, setEventId] = useState("");
  const [price, setPrice] = useState("");
  const [origPrice, setOrigPrice] = useState("");
  const [qrFile, setQrFile] = useState<File[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [suggestion, setSuggestion] = useState<Suggestion | null>(null);

  useEffect(() => {
    api.get("/cities").then(({ data }) => setCities(data ?? [])).catch(() => setCities([]));
  }, []);

  // Seed from the navbar selection so the seller does not pick a city twice.
  useEffect(() => {
    if (selected?.id) setCityId(selected.id);
  }, [selected?.id]);

  useEffect(() => {
    if (!cityId) { setEvents([]); setEventId(""); return; }
    api
      .get("/events", { params: { city_id: cityId } })
      .then(({ data }) => { setEvents(data ?? []); setEventId(""); })
      .catch(() => setEvents([]));
  }, [cityId]);

  const face = parseFloat(origPrice) || 0;
  const ask = parseFloat(price) || 0;

  // The cap is deterministic and comes from the server. It is a rule, not a
  // recommendation — the pricing model (when it lands) advises *within* it.
  const cap = face > 0 ? face * config.price_cap_multiplier : 0;
  const overCap = cap > 0 && ask > cap;

  const deposit = ask > 0 ? ask * config.listing_fee_rate : 0;
  const compensation = ask > 0 ? ask * config.buyer_compensation_rate : 0;
  // Shown before they commit. A seller should never discover the commission
  // on the payout screen after the sale has already happened.
  const commission = ask > 0 ? ask * config.seller_success_fee_rate : 0;

  const canSubmit = useMemo(
    () => Boolean(cityId && eventId && face > 0 && ask > 0 && !overCap && qrFile[0]),
    [cityId, eventId, face, ask, overCap, qrFile]
  );

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

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);

    try {
      setAuthToken(await getToken());

      const form = new FormData();
      form.append("event_id", eventId);
      form.append("city_id", cityId);
      form.append("price", price);
      form.append("original_price", origPrice);
      form.append("quantity", "1");
      form.append("qr_file", qrFile[0]);

      const { data: listing } = await api.post("/listings/create", form);
      const listingId = listing.listing_id;

      // Log what we suggested against what they actually chose. This is the
      // future training set and the live calibration check — and it is the one
      // thing here that cannot be back-filled later. Never block the listing
      // on it.
      if (suggestion) {
        api
          .post("/pricing/recommendations", {
            event_id: eventId,
            listing_id: listingId,
            face_value: face,
            p25: suggestion.p25_paise / 100,
            p50: suggestion.p50_paise / 100,
            p75: suggestion.p75_paise / 100,
            cap: suggestion.cap_paise / 100,
            sell_probability: suggestion.sell_probability,
            source: suggestion.source,
            model_version: suggestion.model_version,
            chosen_price: ask,
          })
          .catch(() => {});
      }

      const { data: fee } = await api.post(`/listings/${listingId}/initiate-fee`);
      await loadRazorpay();

      const rzp = new window.Razorpay({
        key: fee.razorpay_key_id,
        amount: Math.round(fee.amount * 100),
        currency: "INR",
        name: "TicketVault",
        description: "Refundable security deposit",
        order_id: fee.razorpay_order_id,
        theme: { color: "#f59e0b" },
        handler: async (res: any) => {
          try {
            setAuthToken(await getToken());
            await api.post(`/listings/${listingId}/verify-fee`, {
              razorpay_order_id: res.razorpay_order_id,
              razorpay_payment_id: res.razorpay_payment_id,
              razorpay_signature: res.razorpay_signature,
            });
            toast.success("Your listing is live", {
              description: "Your deposit is held and returned when the ticket transfers.",
            });
            router.push("/dashboard");
          } catch (e: any) {
            toast.error("Deposit not confirmed", { description: e.message });
          }
        },
        modal: {
          ondismiss: () => {
            setSubmitting(false);
            toast.warning("Listing saved, deposit unpaid", {
              description: "It won't be visible to buyers until the deposit is paid. Finish from your dashboard.",
            });
            router.push("/dashboard");
          },
        },
      });

      rzp.open();
    } catch (e: any) {
      toast.error("Could not create the listing", { description: e.message });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="container max-w-2xl py-14">
      <p className="eyebrow mb-2">Sell a ticket</p>
      <h1 className="font-display text-5xl tracking-display">LIST YOUR TICKET</h1>
      <p className="mt-2 text-sm text-muted-foreground">
        One ticket per listing. You&apos;ll transfer it through your ticketing app
        once someone buys.
      </p>

      <div className="mt-10 space-y-6">
        <div className="grid gap-5 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="city">City</Label>
            <Select value={cityId} onValueChange={setCityId}>
              <SelectTrigger id="city">
                <SelectValue placeholder="Select a city" />
              </SelectTrigger>
              <SelectContent>
                {cities.map((c) => (
                  <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label htmlFor="event">Event</Label>
            <Select value={eventId} onValueChange={setEventId} disabled={!cityId}>
              <SelectTrigger id="event">
                <SelectValue
                  placeholder={
                    !cityId ? "Pick a city first"
                      : events.length === 0 ? "No events in this city"
                      : "Select an event"
                  }
                />
              </SelectTrigger>
              <SelectContent>
                {events.map((e) => (
                  <SelectItem key={e.id} value={e.id}>
                    {e.title ?? e.name}
                    {e.date ? ` · ${new Date(e.date).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}` : ""}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        {/* Sellers cannot create events directly — the catalogue is the trust
            surface. They propose, an admin approves. */}
        <div className="flex items-center justify-between rounded-md border border-dashed border-border px-4 py-3">
          <p className="text-sm text-muted-foreground">Can&apos;t find your event?</p>
          <RequestEventDialog cities={cities} defaultCityId={cityId} />
        </div>

        <Separator perforated />

        <div className="grid gap-5 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="face">Face value (₹)</Label>
            <Input
              id="face" type="number" min="1" inputMode="numeric"
              value={origPrice} onChange={(e) => setOrigPrice(e.target.value)}
              placeholder="0" className="tnum font-mono"
            />
            <p className="text-xs text-muted-foreground">What you originally paid.</p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="ask">Your price (₹)</Label>
            <Input
              id="ask" type="number" min="1" inputMode="numeric"
              value={price} onChange={(e) => setPrice(e.target.value)}
              placeholder="0"
              className={`tnum font-mono ${overCap ? "border-destructive focus-visible:border-destructive" : ""}`}
              aria-invalid={overCap}
            />
            {cap > 0 && (
              <p className={`text-xs ${overCap ? "text-destructive" : "text-muted-foreground"}`}>
                {overCap
                  ? `Capped at ${inr(cap)}.`
                  : `Maximum ${inr(cap)}.`}
              </p>
            )}
          </div>
        </div>

        {/* Guidance appears as soon as the face value is known — before the
            seller commits to a number. Advisory only; the cap below is what
            actually enforces anything. */}
        {face > 0 && (
          <PriceGuidance
            faceValue={face}
            eventId={eventId || undefined}
            price={ask || null}
            onPriceChange={(next, s) => {
              setPrice(String(next));
              if (s) setSuggestion(s);
            }}
          />
        )}

        {overCap && (
          <div className="flex gap-3 rounded-md border border-destructive/40 bg-destructive/10 p-4">
            <AlertTriangle className="mt-0.5 size-4 shrink-0 text-destructive" />
            <div className="text-sm">
              <p className="font-medium text-destructive">
                That&apos;s above the {Math.round((config.price_cap_multiplier - 1) * 100)}% cap
              </p>
              <p className="mt-1 text-muted-foreground">
                We cap resale at {inr(cap)} for this ticket so buyers know they&apos;re
                never being gouged. It&apos;s the reason they trust us over a group chat.
              </p>
            </div>
          </div>
        )}

        {/* Deposit explainer. Rate comes from GET /config, never hardcoded. */}
        {ask > 0 && !overCap && (
          <div className="rounded-lg border border-border bg-card p-5">
            <div className="flex items-center gap-2">
              <ShieldCheck className="size-4 text-primary" />
              <p className="font-display text-xl tracking-display">
                REFUNDABLE DEPOSIT
              </p>
            </div>

            <div className="mt-4 flex items-baseline justify-between">
              <span className="text-sm text-muted-foreground">
                {Math.round(config.listing_fee_rate * 100)}% of your price, paid now
              </span>
              <span className="tnum font-mono text-2xl text-primary">{inr(deposit)}</span>
            </div>

            <div className="perforation my-4" />

            <ul className="space-y-2.5 text-sm">
              <li className="flex gap-2.5">
                <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success" />
                <span className="text-muted-foreground">
                  You get <span className="text-foreground">all of it back</span>, plus{" "}
                  <span className="text-foreground">{inr(ask - commission)}</span> from
                  the sale, once the buyer confirms the transfer.
                </span>
              </li>
              <li className="flex gap-2.5">
                <Info className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                <span className="text-muted-foreground">
                  If you don&apos;t transfer within {config.transfer_sla_hours} hours,
                  the buyer is refunded and paid {inr(compensation)} from this deposit.
                </span>
              </li>
            </ul>
          </div>
        )}

        <div className="space-y-2">
          <Label>Proof of ownership</Label>
          <p className="text-xs text-muted-foreground">
            Upload your ticket&apos;s QR. This is <span className="text-foreground">not</span> sent
            to the buyer. You&apos;ll transfer the real ticket through your ticketing
            app. It only proves to us that the ticket exists.
          </p>
          <QRUpload count={1} onChange={setQrFile} />
        </div>

        <Button
          size="lg"
          className="w-full"
          onClick={handleSubmit}
          disabled={!canSubmit}
          loading={submitting}
        >
          {ask > 0 && !overCap ? `Pay ${inr(deposit)} deposit & publish` : "List ticket"}
        </Button>
      </div>
    </div>
  );
}
