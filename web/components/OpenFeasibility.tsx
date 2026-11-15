"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

/** NCT id -> /feasibility/[nct]. `defaultNct` prefills the field (remount with a new `key` to
 *  apply one that arrives after the first render). */
export function OpenFeasibility({ defaultNct }: { defaultNct?: string | null }) {
  const router = useRouter();
  const [nct, setNct] = useState(defaultNct ?? "");
  const id = nct.trim().toUpperCase();
  return (
    <form
      className="flex gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (id) router.push(`/feasibility/${encodeURIComponent(id)}`);
      }}
    >
      <Input
        value={nct}
        onChange={(e) => setNct(e.target.value)}
        placeholder="NCT ID"
        aria-label="NCT ID"
        spellCheck={false}
        autoCapitalize="characters"
        className="min-w-0 flex-1 font-mono sm:max-w-56"
      />
      <Button type="submit" disabled={!id}>
        Open
      </Button>
    </form>
  );
}
