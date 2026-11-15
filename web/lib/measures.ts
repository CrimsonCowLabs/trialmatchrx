// Display labels for lab and vital keys (PatientFacts.labs / .vitals), shared by the facts strip
// and the patient facts panel.

const MEASURE_LABELS: Record<string, string> = {
  hba1c: "HbA1c",
  egfr: "eGFR",
  uacr: "UACR",
  upcr: "UPCR",
  potassium: "Potassium",
  ldl: "LDL",
  creatinine: "Creatinine",
  albumin: "Albumin",
  alt: "ALT",
  hscrp: "hs-CRP",
  fvc_pct: "FVC (% pred)",
  fev1_pct: "FEV1 (% pred)",
  fev1_fvc: "FEV1/FVC",
  svc_pct: "SVC (% pred)",
  dlco_pct: "DLCO (% pred)",
  alsfrs_r: "ALSFRS-R",
  six_mwd: "6-minute walk",
  pvr: "PVR",
  pcwp: "PCWP",
  bmi: "BMI",
  sbp: "Systolic BP",
  dbp: "Diastolic BP",
  weight: "Weight",
};

/** "FVC (% pred)" for `fvc_pct`; an unknown key reads as itself, de-snaked ("nt_probnp" ->
 *  "Nt probnp", a trailing `_pct` as "(% pred)"). */
export function measureLabel(key: string): string {
  const known = MEASURE_LABELS[key];
  if (known) return known;
  const pct = key.endsWith("_pct");
  const words = (pct ? key.slice(0, -4) : key).replace(/_/g, " ").trim();
  const text = words.charAt(0).toUpperCase() + words.slice(1);
  return pct ? `${text} (% pred)` : text;
}
