"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { CalendarClock, Pencil, TriangleAlert } from "lucide-react";

import { api } from "@/lib/api";
import { formatEventDate, inr } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter,
  DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";

interface City { id: string; name?: string }

/** datetime-local wants `YYYY-MM-DDTHH:mm` in LOCAL time, not an ISO string. */
function toLocalInput(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(
    d.getHours()
  )}:${pad(d.getMinutes())}`;
}

// ── Edit / postpone ──────────────────────────────────────────────────────────

export function EditEventDialog({
  event,
  cities,
  onDone,
}: {
  event: any;
  cities: City[];
  onDone: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);

  const [title, setTitle] = useState(event.title ?? "");
  const [venue, setVenue] = useState(event.venue ?? "");
  const [cityId, setCityId] = useState(event.city_id ?? "");
  const [date, setDate] = useState(toLocalInput(event.date));
  const [imageUrl, setImageUrl] = useState(event.image_url ?? "");
  const [tier, setTier] = useState(String(event.popularity_tier ?? 3));

  const reset = () => {
    setTitle(event.title ?? "");
    setVenue(event.venue ?? "");
    setCityId(event.city_id ?? "");
    setDate(toLocalInput(event.date));
    setImageUrl(event.image_url ?? "");
    setTier(String(event.popularity_tier ?? 3));
  };

  const dateChanged =
    date && new Date(date).getTime() !== new Date(event.date).getTime();

  const save = async () => {
    setSaving(true);
    try {
      await api.patch(`/admin/events/${event.id}`, {
        title: title.trim(),
        venue: venue.trim(),
        city_id: cityId,
        date: date ? new Date(date).toISOString() : undefined,
        image_url: imageUrl.trim() || null,
        popularity_tier: Number(tier),
      });
      toast.success(dateChanged ? "Concert rescheduled" : "Concert updated", {
        description: dateChanged
          ? "Existing tickets stay valid for the new date."
          : undefined,
      });
      setOpen(false);
      onDone();
    } catch (e: any) {
      toast.error("Couldn't save", { description: e.message });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => { setOpen(o); if (o) reset(); }}>
      <DialogTrigger asChild>
        <Button size="sm" variant="ghost" disabled={Boolean(event.cancelled_at)}>
          <Pencil />
          Edit
        </Button>
      </DialogTrigger>

      <DialogContent>
        <DialogHeader>
          <DialogTitle>EDIT CONCERT</DialogTitle>
          <DialogDescription>{event.title}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4 p-5">
          <div className="space-y-2">
            <Label htmlFor="ev-title">Name</Label>
            <Input id="ev-title" value={title} onChange={(e) => setTitle(e.target.value)} />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="ev-venue">Venue</Label>
              <Input id="ev-venue" value={venue} onChange={(e) => setVenue(e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="ev-city">City</Label>
              <Select value={cityId} onValueChange={setCityId}>
                <SelectTrigger id="ev-city"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {cities.map((c) => (
                    <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="ev-date">Date & time</Label>
              <Input
                id="ev-date" type="datetime-local" className="tnum"
                value={date} onChange={(e) => setDate(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="ev-tier">Popularity (1 to 5)</Label>
              <Select value={tier} onValueChange={setTier}>
                <SelectTrigger id="ev-tier"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {[1, 2, 3, 4, 5].map((t) => (
                    <SelectItem key={t} value={String(t)}>{t}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="ev-image">Poster URL</Label>
            <Input
              id="ev-image" type="url" value={imageUrl}
              onChange={(e) => setImageUrl(e.target.value)} placeholder="https://..."
            />
          </div>

          {/* Says plainly what a date change does, because the intuitive
              expectation is that everyone gets refunded and that is not what
              happens. */}
          {dateChanged && (
            <div className="flex gap-3 rounded-md border border-primary/40 bg-primary/5 p-4 text-sm">
              <CalendarClock className="mt-0.5 size-4 shrink-0 text-primary" />
              <div>
                <p className="font-medium">This is a postponement</p>
                <p className="mt-1 text-muted-foreground">
                  Tickets already sold stay valid and nobody is refunded, which
                  matches how the ticketing apps treat a rescheduled show. The
                  original date is kept on record. A buyer who can&apos;t make
                  the new date can report a problem.
                </p>
              </div>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
          <Button onClick={save} loading={saving} disabled={!title.trim() || !venue.trim()}>
            Save changes
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── Cancel ───────────────────────────────────────────────────────────────────

export function CancelEventDialog({
  event,
  onDone,
}: {
  event: any;
  onDone: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [impact, setImpact] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [reason, setReason] = useState("");
  const [cancelling, setCancelling] = useState(false);

  // Load the blast radius when the dialog opens. Refunding a room full of
  // buyers should not be something you discover the size of afterwards.
  useEffect(() => {
    if (!open) return;
    setLoading(true);
    api
      .get(`/admin/events/${event.id}/cancel-impact`)
      .then(({ data }) => setImpact(data))
      .catch(() => setImpact(null))
      .finally(() => setLoading(false));
  }, [open, event.id]);

  const cancel = async () => {
    setCancelling(true);
    try {
      const { data } = await api.post(`/admin/events/${event.id}/cancel`, {
        reason: reason.trim(),
      });
      toast.success("Concert cancelled", {
        description:
          `${data.refunded?.length ?? 0} buyers refunded, ` +
          `${data.deposits_returned?.length ?? 0} deposits returned.`,
      });
      setOpen(false);
      setReason("");
      onDone();
    } catch (e: any) {
      toast.error("Couldn't cancel", { description: e.message });
    } finally {
      setCancelling(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          size="sm" variant="ghost"
          className="text-destructive hover:bg-destructive/10"
          disabled={Boolean(event.cancelled_at)}
        >
          <TriangleAlert />
          Cancel
        </Button>
      </DialogTrigger>

      <DialogContent>
        <DialogHeader>
          <DialogTitle>CANCEL CONCERT</DialogTitle>
          <DialogDescription>
            {event.title}, {formatEventDate(event.date).full}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 p-5">
          {loading ? (
            <Skeleton className="h-32" />
          ) : impact ? (
            <div className="rounded-md border border-destructive/40 bg-destructive/5 p-4">
              <p className="eyebrow mb-3">What this will do</p>
              <dl className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <dt className="text-muted-foreground">Buyers refunded</dt>
                  <dd className="tnum font-mono">
                    {impact.bookings_to_refund} ·{" "}
                    {inr(impact.refund_total_paise / 100)}
                  </dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-muted-foreground">Deposits returned</dt>
                  <dd className="tnum font-mono">
                    {impact.deposits_to_return} ·{" "}
                    {inr(impact.deposit_total_paise / 100)}
                  </dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-muted-foreground">Listings withdrawn</dt>
                  <dd className="tnum font-mono">{impact.listings_total}</dd>
                </div>
              </dl>

              <p className="mt-3 border-t border-border pt-3 text-xs text-muted-foreground">
                Sellers get their deposits back in full. A promoter calling off
                a show is nothing to do with them, so nothing is forfeited.
              </p>

              {impact.already_paid_out > 0 && (
                <p className="mt-2 text-xs text-destructive">
                  {impact.already_paid_out} booking
                  {impact.already_paid_out === 1 ? " has" : "s have"} already
                  been paid out and cannot be reversed from here.
                </p>
              )}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              Couldn&apos;t load the impact. Cancelling is still possible, but
              you will not see the numbers first.
            </p>
          )}

          <div className="space-y-2">
            <Label htmlFor="cancel-reason">Why</Label>
            <Textarea
              id="cancel-reason" value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="e.g. Promoter cancelled the tour leg."
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={() => setOpen(false)}>Keep it</Button>
          <Button
            variant="destructive"
            loading={cancelling}
            disabled={reason.trim().length < 3}
            onClick={cancel}
          >
            Cancel and refund everyone
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
