"use client";

import { RotateCcw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ruleLabel, sliderRange, type WaterfallStep } from "@/lib/feasibility";

/** A numeric rule's threshold. Moves locally on every input; the page debounces the API call. */
export function ThresholdSlider({
  step,
  value,
  onChange,
  onReset,
}: {
  step: WaterfallStep;
  value: number;
  onChange: (value: number) => void;
  onReset: () => void;
}) {
  const range = sliderRange(step);
  const changed = typeof step.default_value === "number" && value !== step.default_value;
  const label = ruleLabel({ ...step, value });
  return (
    <div className="flex items-center gap-2">
      <input
        type="range"
        min={range.min}
        max={range.max}
        step={range.step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        aria-label={`${step.criterion_id} threshold`}
        aria-valuetext={label}
        className="h-1.5 w-full min-w-24 cursor-pointer accent-primary"
      />
      {/* Below sm the row prints the rule above its Adjust link. */}
      <span className="hidden w-36 shrink-0 font-mono text-xs tabular-nums sm:inline">{label}</span>
      <Button
        variant="ghost"
        size="icon-xs"
        onClick={onReset}
        disabled={!changed}
        aria-label={`Reset ${step.criterion_id} to ${String(step.default_value)}`}
        title={`Trial value: ${String(step.default_value)}`}
      >
        <RotateCcw />
      </Button>
    </div>
  );
}
