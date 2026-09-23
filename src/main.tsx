import { debugLog } from "./lib/logging";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { AppProviders } from "@/app/providers";
import "@/styles/globals.css";

performance.mark("kicktrack-react-start");

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AppProviders>
      <App />
    </AppProviders>
  </StrictMode>,
);

requestAnimationFrame(() => {
  performance.mark("kicktrack-first-paint");
  performance.measure("kicktrack-react-to-paint", "kicktrack-react-start", "kicktrack-first-paint");
  const entries = performance.getEntriesByName("kicktrack-react-to-paint");
  const measurement = entries.length ? entries[entries.length - 1] : undefined;
  if (measurement) debugLog(`[KickTrack startup] React → first paint: ${measurement.duration.toFixed(0)} ms`);
});
