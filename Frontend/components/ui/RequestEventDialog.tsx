"use client";

import { useState } from "react";
import { toast } from "sonner";
import { PlusCircle } from "lucide-react";

import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter,
  DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";

interface Option { id: string; name?: string }

/**
 * Sellers propose events; an admin approves them into the catalogue.
 *
 * They cannot insert events directly — a seller who can create arbitrary
 * events can invent one that does not exist, list a ticket against it, and
 * take money for something nobody can verify.
 */
export function RequestEventDialog({
  cities,
  defaultCityId,
}: {
  cities: Option[];
  defaultCityId?: string;
}) {
  const [open, setOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const [title, setTitle] = useState("");
  const [venue, setVenue] = useState("");
  const [cityId, setCityId] = useState(defaultCityId ?? "");
  const [date, setDate] = useState("");
  const [evidenceUrl, setEvidenceUrl] = useState("");
  const [notes, setNotes] = useState("");

  const valid = title.trim().length >= 3 && venue.trim().length >= 2 && cityId && date;

  const submit = async () => {
    if (!valid) return;
    setSubmitting(true);
    try {
      await api.post("/events/requests", {
        title: title.trim(),
        venue: venue.trim(),
        city_id: cityId,
        date: new Date(date).toISOString(),
        evidence_url: evidenceUrl.trim() || null,
        notes: notes.trim() || null,
      });
      toast.success("Sent for review", {
        description: "We'll add the event once an admin confirms it. You'll see the status on your dashboard.",
      });
      setOpen(false);
      setTitle(""); setVenue(""); setDate(""); setEvidenceUrl(""); setNotes("");
    } catch (e: any) {
      toast.error("Couldn't submit the request", { description: e.message });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          <PlusCircle />
          Request it
        </Button>
      </DialogTrigger>

      <DialogContent>
        <DialogHeader>
          <DialogTitle>REQUEST AN EVENT</DialogTitle>
          <DialogDescription>
            Tell us about the show and we&apos;ll add it to the catalogue once
            we&apos;ve confirmed it exists. Usually within a day.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 p-5">
          <div className="space-y-2">
            <Label htmlFor="req-title">Event name</Label>
            <Input
              id="req-title" value={title} onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. Diljit Dosanjh Dil-Luminati Tour"
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="req-venue">Venue</Label>
              <Input
                id="req-venue" value={venue} onChange={(e) => setVenue(e.target.value)}
                placeholder="e.g. JLN Stadium"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="req-city">City</Label>
              <Select value={cityId} onValueChange={setCityId}>
                <SelectTrigger id="req-city">
                  <SelectValue placeholder="Select a city" />
                </SelectTrigger>
                <SelectContent>
                  {cities.map((c) => (
                    <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="req-date">Date & time</Label>
            <Input
              id="req-date" type="datetime-local"
              value={date} onChange={(e) => setDate(e.target.value)}
              className="tnum"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="req-evidence">Link to the event (optional)</Label>
            <Input
              id="req-evidence" type="url" value={evidenceUrl}
              onChange={(e) => setEvidenceUrl(e.target.value)}
              placeholder="https://..."
            />
            <p className="text-xs text-muted-foreground">
              A booking page or announcement. Requests with a link get approved faster.
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="req-notes">Anything else (optional)</Label>
            <Textarea
              id="req-notes" value={notes} onChange={(e) => setNotes(e.target.value)}
              placeholder="Seat category, tour leg, anything that helps us identify it."
              maxLength={1000}
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
          <Button onClick={submit} disabled={!valid} loading={submitting}>
            Send request
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
