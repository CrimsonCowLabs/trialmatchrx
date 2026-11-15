"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

/** NCT id -> /feasibility/[nct]. */
export function OpenFeasibility() {
  const router = useRouter();
  const [nct, setNct] = useState("");
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
        placeholder="NCT07271186"
        aria-label="NCT id"
        className="max-w-48 font-mono"
      />
      <Button type="submit" variant="outline" disabled={!id}>
        Trial feasibility
      </Button>
    </form>
  );
}
