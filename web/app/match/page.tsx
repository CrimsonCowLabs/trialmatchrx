"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";

// HACK(demo): prefilled synthetic demo patient from SPEC.md; condition and radius defaults too.
const DEMO_NOTE =
  "61-year-old man with type 2 diabetes, HbA1c 8.4%, eGFR 48, on metformin. Lives in Sacramento.";

export default function MatchPage() {
  const router = useRouter();
  const [note, setNote] = useState(DEMO_NOTE);
  const [condition, setCondition] = useState("type 2 diabetes");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { run_id } = await api.startMatch({ note, condition, radius_mi: 50 });
      router.push(`/match/${run_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto flex w-full max-w-2xl flex-col gap-4 p-8">
      <h1 className="text-2xl font-semibold">Match a patient</h1>
      <form onSubmit={onSubmit} className="flex flex-col gap-3">
        <label className="flex flex-col gap-1 text-sm">
          Patient note
          <Textarea
            name="note"
            rows={6}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            required
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          Condition
          <Input name="condition" value={condition} onChange={(e) => setCondition(e.target.value)} />
        </label>
        <Button type="submit" disabled={busy || !note.trim()}>
          {busy ? "Starting…" : "Find trials"}
        </Button>
        {error && <p className="text-sm text-destructive">{error}</p>}
      </form>
    </main>
  );
}
