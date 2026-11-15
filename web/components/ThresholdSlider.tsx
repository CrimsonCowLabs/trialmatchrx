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
  const changed = typeof step.defaultValue === "number" && value !== step.defaultValue;
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
        aria-label={`${step.criterionId} threshold`}
        aria-valuetext={label}
        className="h-1.5 w-full min-w-24 cursor-pointer accent-primary"
      />
      <span className="w-36 shrink-0 font-mono text-xs tabular-nums">{label}</span>
      <Button
        variant="ghost"
        size="icon-xs"
        onClick={onReset}
        disabled={!changed}
        aria-label={`Reset ${step.criterionId} to ${String(step.defaultValue)}`}
        title={`Trial value: ${String(step.defaultValue)}`}
      >
        <RotateCcw />
      </Button>
    </div>
  );
}
