import type { ComponentType } from "react";
import Cashflow from "./Cashflow";
import Overview from "./Overview";
import Summary from "./Summary";
import Goals from "./Goals";
import Recommendations from "./Recommendations";
import Networth from "./Networth";
import Portfolio from "./Portfolio";
import Metrics from "./Metrics";
import Timeline from "./Timeline";
import MyPlan from "./MyPlan";

export interface RouteDef {
  path: string;
  label: string; // Hebrew nav label
  Component: ComponentType;
}

/** Mirrors the 10 PRD features in docs/plangram-prd. Order = nav order. */
export const routes: RouteDef[] = [
  { path: "/overview", label: "מבט על", Component: Overview },
  { path: "/cashflow", label: "תזרים כספי", Component: Cashflow },
  { path: "/summary", label: "סיכום התוכנית", Component: Summary },
  { path: "/goals", label: "יעדים", Component: Goals },
  { path: "/recommendations", label: "המלצות", Component: Recommendations },
  { path: "/networth", label: "שווי נקי", Component: Networth },
  { path: "/portfolio", label: "השקעות", Component: Portfolio },
  { path: "/metrics", label: "התקדמות", Component: Metrics },
  { path: "/timeline", label: "ציר זמן", Component: Timeline },
  { path: "/my-plan", label: "תכנון פלוס", Component: MyPlan },
];
