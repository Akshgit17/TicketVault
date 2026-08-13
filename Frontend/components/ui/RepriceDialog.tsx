"use client";

import { useState } from "react";
import { toast } from "sonner";
import { Pencil } from "lucide-react";

import { api } from "@/lib/api";
import { inr } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { PriceGuidance, type Suggestion } from "@/components/ui/PriceGuidance";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter,
  DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";

/**
 * Change the price of a live listing.
 *
 * Reuses the full pricing slider rather than a bare number field, because
 * repricing is precisely when the guidance is worth having: the seller is here
 * because the first price did not work. Showing the band and the live
 * sell-probability at that moment is more useful than showing it at listing
 * time, when they had no evidence either way.
 *
 * The deposit is deliberately not recalculated. It was taken as a percentage
 * of the original ask and is returned in full on a completed sale, so being
 * over- or under-collateralised costs the seller nothing. The server refuses
 * only a rise the existing deposit could no longer cover if the sale failed.
 */
export function RepriceDialog({
  listing,
  onDone,
}: {
  listing: {
    id: string;
    price: number;
    original_price: number;
    event_id?: string;
    events?: { id?: string; title?: string } | null;
  };
  onDone: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [price, setPrice] = useState<number | null>(Number(listing.price));
  const [suggestion, setSuggestion] = useState<Suggestion | null>(null);
  const [saving, setSaving] = useState(false);

  const current = Number(listing.price);
  const changed = price != null && Math.round(price) !== Math.round(current);

  const save = async () => {
    if (!price || !changed) return;
    setSaving(true);
    try {
      await api.post(`/listings/${listing.id}/price`, { price });
      toast.success("Price updated", {
        description: `Now listed at ${inr(price)}.`,
      });
      setOpen(false);
      onDone();
    } catch (e: any) {
      toast.error("Couldn't update the price", { description: e.message });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        setOpen(o);
        // Reset to the live price each time, so an abandoned edit does not
        // linger and get saved by accident later.
        if (o) setPrice(current);
      }}
    >
      <DialogTrigger asChild>
        <Button size="sm" variant="ghost">
          <Pencil />
          Reprice
        </Button>
      </DialogTrigger>

      <DialogContent>
        <DialogHeader>
          <DialogTitle>CHANGE YOUR PRICE</DialogTitle>
          <DialogDescription>
            {listing.events?.title ?? "Your listing"}, currently at{" "}
            {inr(current)}.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 p-5">
          <PriceGuidance
            faceValue={Number(listing.original_price)}
            eventId={listing.events?.id ?? listing.event_id}
            price={price}
            onPriceChange={(next, s) => {
              setPrice(next);
              if (s) setSuggestion(s);
            }}
          />

          {changed && (
            <p className="text-sm text-muted-foreground">
              Changing from{" "}
              <span className="tnum font-mono">{inr(current)}</span> to{" "}
              <span className="tnum font-mono text-foreground">
                {inr(price!)}
              </span>
              . Your deposit stays as it is and still comes back in full when
              the ticket transfers.
            </p>
          )}
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
          <Button onClick={save} disabled={!changed} loading={saving}>
            Update price
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
