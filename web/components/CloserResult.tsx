"use client";

// The closer agent's answer for one trial: a follow-up per unknown criterion, the draft email
// to the study coordinator, and the patient summary in English and Spanish side by side.
import { ClipboardCheck, FlaskConical, MessageCircleQuestion } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { CloserOutput } from "@/lib/api";

type Followup = CloserOutput["followups"][number];

const KIND: Record<Followup["kind"], { icon: typeof FlaskConical; label: string }> = {
  test: { icon: FlaskConical, label: "Test" },
  question: { icon: MessageCircleQuestion, label: "Ask" },
};

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <Button
      variant="outline"
      size="xs"
      onClick={() =>
        navigator.clipboard.writeText(text).then(
          () => setCopied(true),
          () => setCopied(false),
        )
      }
    >
      <ClipboardCheck /> {copied ? "Copied" : "Copy"}
    </Button>
  );
}

export function CloserResult({ output }: { output: CloserOutput }) {
  const email = output.coordinator_email;
  const emailText = `To: ${email.to ?? "(study team)"}\nSubject: ${email.subject}\n\n${email.body}`;
  return (
    <div className="flex flex-col gap-4" data-testid="closer-result">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            Follow-ups <Badge variant="outline">{output.followups.length}</Badge>
          </CardTitle>
          <p className="text-xs text-muted-foreground">
            One per unknown criterion of {output.nct_id}: the test or question that resolves it
          </p>
        </CardHeader>
        <CardContent>
          <ul className="flex flex-col divide-y">
            {output.followups.map((f) => {
              const { icon: Icon, label } = KIND[f.kind];
              return (
                <li key={f.criterion_id} className="flex gap-3 py-2" data-testid="followup">
                  <Icon className="mt-0.5 size-4 shrink-0 text-verdict-unknown" aria-hidden />
                  <div className="flex min-w-0 flex-col gap-0.5">
                    <p className="text-sm">
                      <span className="font-mono text-xs text-muted-foreground">
                        {f.criterion_id}
                      </span>{" "}
                      <Badge variant="secondary">{label}</Badge> {f.action}
                    </p>
                    <p className="text-xs text-muted-foreground">{f.why}</p>
                  </div>
                </li>
              );
            })}
          </ul>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between gap-2">
            Email to the study coordinator <CopyButton text={emailText} />
          </CardTitle>
          <p className="text-xs text-muted-foreground">
            To <span className="font-mono break-all">{email.to ?? "(no contact email listed)"}</span>
          </p>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          <p className="text-sm font-medium">{email.subject}</p>
          <p className="text-sm whitespace-pre-wrap">{email.body}</p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Patient summary</CardTitle>
          <p className="text-xs text-muted-foreground">6th-grade reading level</p>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          {(
            [
              ["en", "English", output.patient_summary.en],
              ["es", "Español", output.patient_summary.es],
            ] as const
          ).map(([lang, title, text]) => (
            <section key={lang} lang={lang} className="flex flex-col gap-1">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {title}
              </h3>
              <p className="text-sm">{text}</p>
            </section>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
