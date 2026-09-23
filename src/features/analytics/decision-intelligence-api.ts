import { invoke } from "@tauri-apps/api/core";
import type { FairValueReferenceResponse, FixtureOutlookResponse } from "./decision-intelligence";

export function getFairValueReference() {
  return invoke<FairValueReferenceResponse>("fair_value_reference");
}

export function getFixtureOutlook() {
  return invoke<FixtureOutlookResponse>("fixture_outlook");
}
