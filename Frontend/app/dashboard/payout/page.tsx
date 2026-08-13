"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useAuth } from "@clerk/nextjs";
import { toast } from "sonner";
import { ArrowLeft, FlaskConical, Info, Landmark, Lock, ShieldCheck } from "lucide-react";

import { api, setAuthToken } from "@/lib/api";
import { inr } from "@/lib/utils";
import { Badge, type BadgeProps } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";

interface PayoutStatus {
  configured: boolean;
  kyc_status: string;
  payout_hold: boolean;
  account_last4: string | null;
  ifsc: string | null;
  beneficiary_name: string | null;
  can_receive_payouts: boolean;
}

const KYC: Record<string, { label: string; tone: BadgeProps["variant"] }> = {
  none:     { label: "Not started",  tone: "neutral" },
  pending:  { label: "In progress",  tone: "default" },
  verified: { label: "Verified",     tone: "success" },
  rejected: { label: "Rejected",     tone: "destructive" },
};

export default function PayoutPage() {
  const { getToken } = useAuth();

  const [status, setStatus] = useState<PayoutStatus | null>(null);
  const [earnings, setEarnings] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const [form, setForm] = useState({
    account_number: "",
    confirm_account: "",
    ifsc: "",
    beneficiary_name: "",
    pan: "",
  });

  const load = useCallback(async () => {
    try {
      setAuthToken(await getToken());
      const [p, e] = await Promise.allSettled([
        api.get("/sellers/me/payout"),
        api.get("/sellers/me/earnings"),
      ]);
      if (p.status === "fulfilled") setStatus(p.value.data);
      if (e.status === "fulfilled") setEarnings(e.value.data);
    } finally {
      setLoading(false);
    }
  }, [getToken]);

  useEffect(() => { load(); }, [load]);

  const submit = async () => {
    // Mistyped account numbers are the most common cause of failed payouts,
    // and the money can be unrecoverable — confirm before sending.
    if (form.account_number !== form.confirm_account) {
      toast.error("Account numbers don't match");
      return;
    }

    setSaving(true);
    try {
      setAuthToken(await getToken());
      const { data } = await api.post("/sellers/me/payout", {
        account_number: form.account_number.trim(),
        ifsc: form.ifsc.trim().toUpperCase(),
        beneficiary_name: form.beneficiary_name.trim(),
        pan: form.pan.trim().toUpperCase(),
      });
      setStatus(data);
      // Drop the sensitive values from component state as soon as they're sent.
      setForm({ account_number: "", confirm_account: "", ifsc: "", beneficiary_name: "", pan: "" });
      toast.success("Payout details saved");
    } catch (e: any) {
      toast.error("Couldn't save those details", { description: e.message });
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="container max-w-2xl space-y-4 py-14">
        <Skeleton className="h-12 w-64" />
        <Skeleton className="h-32" />
        <Skeleton className="h-64" />
      </div>
    );
  }

  const kyc = KYC[status?.kyc_status ?? "none"] ?? KYC.none;
  const hasSimulated = Boolean(
    earnings?.payouts?.some((p: any) => p.simulated)
  );
  // Never sold anything, so the earnings tiles would just read ₹0 twice.
  const neverSold = !earnings?.payouts?.length;
  const valid =
    form.account_number.length >= 9 &&
    form.confirm_account.length >= 9 &&
    form.ifsc.trim().length === 11 &&
    form.beneficiary_name.trim().length >= 3 &&
    form.pan.trim().length === 10;

  return (
    <div className="container max-w-2xl py-14">
      <Button asChild variant="ghost" size="sm" className="mb-6 -ml-3">
        <Link href="/dashboard">
          <ArrowLeft />
          Back to dashboard
        </Link>
      </Button>

      <p className="eyebrow mb-2">Selling</p>
      <h1 className="font-display text-5xl tracking-display">PAYOUT DETAILS</h1>
      <p className="mt-2 text-sm text-muted-foreground">
        Where the money from tickets <span className="text-foreground">you sell</span> is
        sent, along with your returned deposits.
      </p>

      {/* Two ₹0 tiles and a bank form is a confusing first screen for someone
          who has only ever bought a ticket. Refunds are not payouts, so they
          do not belong on this page, but the page should say where they do
          live rather than looking broken. */}
      {neverSold && (
        <div className="mt-8 flex gap-3 rounded-lg border border-border bg-secondary/30 p-5 text-sm">
          <Info className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
          <div>
            <p className="font-medium">You haven&apos;t sold anything yet</p>
            <p className="mt-1 text-muted-foreground">
              This page only covers money coming <span className="text-foreground">to</span> you
              from sales. Refunds on tickets you bought show up on your{" "}
              <Link href="/dashboard" className="text-primary hover:underline">
                dashboard
              </Link>{" "}
              instead, against the booking itself.
            </p>
            <p className="mt-2 text-muted-foreground">
              You can still add your account now so a payout is never held up later.
            </p>
          </div>
        </div>
      )}

      {earnings && !neverSold && (
        <>
          <div className="mt-8 grid gap-px overflow-hidden rounded-lg border border-border bg-border sm:grid-cols-2">
            <div className="bg-card p-5">
              <div className="mb-2 flex items-center gap-2">
                <p className="eyebrow">Paid out</p>
                {hasSimulated && <Badge variant="neutral">simulated</Badge>}
              </div>
              <p className="tnum font-mono text-2xl">
                {inr((earnings.total_paid_paise ?? 0) / 100)}
              </p>
            </div>
            <div className="bg-card p-5">
              <p className="eyebrow mb-2">On the way</p>
              <p className="tnum font-mono text-2xl text-primary">
                {inr((earnings.total_pending_paise ?? 0) / 100)}
              </p>
            </div>
          </div>

          {/* Stated up front rather than left to be discovered. A page that
              says "paid" about money that never moved reads as concealment
              when someone finds it unaided. */}
          {hasSimulated && (
            <div className="mt-4 flex gap-3 rounded-lg border border-primary/40 bg-primary/5 p-4 text-sm">
              <FlaskConical className="mt-0.5 size-4 shrink-0 text-primary" />
              <div>
                <p className="font-medium">These payouts are recorded, not transferred</p>
                <p className="mt-1 text-muted-foreground">
                  Sale proceeds are tracked in full, including the amount, fee split
                  and ledger entry, but no money leaves the platform account.
                  Paying a seller needs Razorpay Route, which has required ₹40
                  lakh turnover since the RBI rules of September 2025.{" "}
                  <span className="text-foreground">
                    Refunds are real:
                  </span>{" "}
                  your returned deposit went back through Razorpay properly.
                </p>
              </div>
            </div>
          )}
        </>
      )}

      <div className="mt-6 rounded-lg border border-border bg-card p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <Landmark className="size-4 text-muted-foreground" />
            <span className="text-sm">
              {status?.configured
                ? `${status.beneficiary_name} · ****${status.account_last4} · ${status.ifsc}`
                : "No account on file"}
            </span>
          </div>
          <Badge variant={kyc.tone}>{kyc.label}</Badge>
        </div>

        {status?.payout_hold && (
          <p className="mt-3 rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
            Payouts are on hold for this account. Contact support.
          </p>
        )}
      </div>

      <Separator perforated className="my-8" />

      <h2 className="font-display text-2xl tracking-display">
        {status?.configured ? "UPDATE YOUR ACCOUNT" : "ADD YOUR ACCOUNT"}
      </h2>

      <div className="mt-5 space-y-5">
        <div className="space-y-2">
          <Label htmlFor="ben">Account holder name</Label>
          <Input
            id="ben" value={form.beneficiary_name}
            onChange={(e) => setForm({ ...form, beneficiary_name: e.target.value })}
            placeholder="As printed on your bank account"
          />
        </div>

        <div className="grid gap-5 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="acc">Account number</Label>
            <Input
              id="acc" value={form.account_number} autoComplete="off"
              onChange={(e) => setForm({ ...form, account_number: e.target.value })}
              className="tnum font-mono"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="acc2">Confirm account number</Label>
            <Input
              id="acc2" value={form.confirm_account} autoComplete="off"
              onChange={(e) => setForm({ ...form, confirm_account: e.target.value })}
              className="tnum font-mono"
            />
          </div>
        </div>

        <div className="grid gap-5 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="ifsc">IFSC code</Label>
            <Input
              id="ifsc" value={form.ifsc} maxLength={11}
              onChange={(e) => setForm({ ...form, ifsc: e.target.value.toUpperCase() })}
              placeholder="HDFC0001234" className="font-mono uppercase"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="pan">PAN</Label>
            <Input
              id="pan" value={form.pan} maxLength={10}
              onChange={(e) => setForm({ ...form, pan: e.target.value.toUpperCase() })}
              placeholder="ABCDE1234F" className="font-mono uppercase"
            />
          </div>
        </div>

        <div className="flex gap-3 rounded-md border border-border bg-secondary/30 p-4 text-sm">
          <Lock className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
          <p className="text-muted-foreground">
            Your account number and PAN are never stored in full and never
            logged. Only the last four digits are kept, so we can show you
            which account is on file.
          </p>
        </div>

        <Button className="w-full" size="lg" disabled={!valid} loading={saving} onClick={submit}>
          <ShieldCheck />
          Save payout details
        </Button>
      </div>
    </div>
  );
}
