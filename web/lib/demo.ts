// The demo patients: the home page and the /match form show them as cards; picking one fills the
// note (still editable) and the condition the search uses.
// api/scripts/record_demo.py mirrors this list by `id` + `note` to pre-record the demo runs; keep
// the two in step when a note changes.
import type { MatchRequest } from "./api";

export interface DemoPatient {
  /** Stable id, shared with api/scripts/record_demo.py. */
  id: "als" | "ipf" | "pah" | "t2d";
  /** Invented display name; every patient here is synthetic. */
  name: string;
  age: number;
  sex: "M" | "F";
  /** Display label for the card. */
  condition: string;
  /** The condition term sent as MatchRequest.condition. */
  searchCondition: string;
  /** One line for the card. */
  summary: string;
  /** The exact note sent to the API. */
  note: string;
}

// HACK(demo): synthetic demo patients for the hackathon demo script (names invented).
export const DEMO_PATIENTS: readonly DemoPatient[] = [
  {
    id: "als",
    name: "Daniel Moreno",
    age: 54,
    sex: "M",
    condition: "ALS",
    searchCondition: "amyotrophic lateral sclerosis",
    summary: "Limb-onset ALS, 14 months in; ALSFRS-R 41, FVC 82%, on riluzole.",
    note: "54-year-old man with ALS (limb onset), symptom onset 14 months ago. ALSFRS-R 41, bulbar subscore 11, breathing subscore 12. FVC 82% predicted. On riluzole 50 mg twice daily for 8 months. No non-invasive ventilation or oxygen use. Lives in Davis, CA.",
  },
  {
    id: "ipf",
    name: "Richard Hale",
    age: 68,
    sex: "M",
    condition: "Idiopathic pulmonary fibrosis",
    searchCondition: "idiopathic pulmonary fibrosis",
    summary: "UIP pattern, FVC 62%, DLCO 38%, mild emphysema; stable on nintedanib.",
    note: "68-year-old man with idiopathic pulmonary fibrosis diagnosed 2 years ago, UIP pattern on HRCT. Former smoker with mild emphysema, less extensive than the fibrosis. FVC 62% predicted, DLCO 38% predicted, FEV1/FVC 0.66. On nintedanib 150 mg twice daily, stable dose for 1 year. No heart failure. Lives in Sacramento, CA.",
  },
  {
    id: "pah",
    name: "Lucía Ramírez",
    age: 47,
    sex: "F",
    condition: "Pulmonary arterial hypertension",
    searchCondition: "pulmonary arterial hypertension",
    summary: "Idiopathic PAH, WHO FC III, PVR 7 WU, 6MWD 380 m; speaks Spanish only.",
    note: "47-year-old woman with idiopathic pulmonary arterial hypertension (WHO Group 1), WHO functional class III. Speaks Spanish only. Right heart catheterization last year: PVR 7 Wood units. 6-minute walk distance 380 m. On ambrisentan and tadalafil, stable for 6 months. BMI 27. Lives in Rancho Cordova, CA.",
  },
  {
    id: "t2d",
    name: "Robert Chen",
    age: 61,
    sex: "M",
    condition: "Type 2 diabetes + CKD",
    searchCondition: "type 2 diabetes",
    summary: "HbA1c 8.4%, eGFR 48, on metformin.",
    note: "61-year-old man with type 2 diabetes, HbA1c 8.4%, eGFR 48, on metformin. Lives in Sacramento.",
  },
];

/** The radius every demo request searches: the seeded reach. */
export const DEMO_RADIUS_MI = 100;

/** The match request for one demo patient. */
export function demoMatchRequest(p: DemoPatient): MatchRequest {
  return { note: p.note, condition: p.searchCondition, radius_mi: DEMO_RADIUS_MI };
}

/** The demo patient whose note this exactly is, or null once the note has been edited. */
export function demoPatientForNote(note: string): DemoPatient | null {
  return DEMO_PATIENTS.find((p) => p.note === note) ?? null;
}
