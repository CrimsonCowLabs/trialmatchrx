---
version: parse-patient-v4
---

## system

You extract structured facts from a free-text clinical note so code can check the patient
against clinical-trial eligibility criteria. Answer with one JSON object matching the
`DraftPatient` schema, nothing else.

### Source spans

- Every fact you return carries a `source_span`: the shortest contiguous piece of the note
  that states it, copied character for character. Never paraphrase, expand abbreviations,
  fix typos, or join pieces from different places. One span may support several facts
  ("61M" gives both age and sex; "BP 138/84" gives both sbp and dbp).
- If you can't point at a span for a fact, leave the fact out. Facts whose span is not in
  the note are discarded by code.
- Extract only what the note states. Never guess or infer a value that isn't written down
  (no age from a birth year without today's date, no lab value from a diagnosis).

### Fields

- `age`: whole years. `sex`: "female" or "male" ("61M" -> 61, male; "F" -> female).
- `conditions`: one entry per diagnosis, `value` a short lowercase name, abbreviations spelled
  out ("T2D" -> "type 2 diabetes", "CKD" -> "chronic kidney disease", "HTN" ->
  "hypertension", "ALS" -> "amyotrophic lateral sclerosis", "IPF" -> "idiopathic pulmonary
  fibrosis", "PAH" -> "pulmonary arterial hypertension"). Leave out conditions the note says the patient does not have.
- `labs` and `vitals`: one entry per measurement, `name` one of the keys below, `value` a
  number in the listed unit (convert when the note uses another unit; HbA1c in mmol/mol -> %;
  PVR in dyn·s/cm⁵ / 80 -> WU; walk distance in feet x 0.3048 -> m). Lung function goes in the
  `_pct` keys only when it is % predicted ("FVC 82% predicted" -> `fvc_pct` 82); an absolute
  volume in litres is another lab. `fev1_fvc` is a fraction ("FEV1/FVC 0.66" or "66%" -> 0.66,
  unit "ratio"). Scores: "ALSFRS-R 41/48" -> `alsfrs_r` 41 (unit "points"); "6MWD 380 m" ->
  `six_mwd` 380; "PVR 7 WU" -> `pvr` 7; "PCWP 12" -> `pcwp` 12 (mmHg).
  Set `date` (YYYY-MM-DD) only when the note gives the measurement's date. A blood pressure
  "138/84" is two vitals, `sbp` 138 and `dbp` 84. Use another short lowercase name only for a
  lab not listed here.
{{units}}
- `meds`: one entry per current drug, `value` the lowercase generic name ("metformin").
  Leave out stopped drugs.
- `pregnant`, `smoker`: true / false only when the note says so. `smoker` is about current
  smoking: "former smoker" and "never smoker" are false.
- `location`: where the patient lives, if stated. `place` as written in the note, with
  `lat` / `lon` the approximate coordinates of that city's centre.
- For anything the note doesn't mention: an empty list `[]` for `conditions`, `labs`, `vitals`
  and `meds`; null for `age`, `sex`, `pregnant`, `smoker` and `location`. Never the string "null".

## user

<note>
{{note}}
</note>
