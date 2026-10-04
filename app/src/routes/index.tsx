import type { ComponentType } from "react";
import {
  ArrowLeftRight,
  CalendarRange,
  ClipboardList,
  Gauge,
  House,
  Landmark,
  Lightbulb,
  PieChart,
  Sparkles,
  Target,
  type LucideIcon,
} from "lucide-react";
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
  icon: LucideIcon;
  /** Pinned to the mobile tab bar; the rest live behind "More". */
  primary?: boolean;
  Component: ComponentType;
}

/** Mirrors the 10 PRD features in docs/plangram-prd. Order = nav order. */
export const routes: RouteDef[] = [
  { path: "/overview", label: "מבט על", icon: House, primary: true, Component: Overview },
  { path: "/cashflow", label: "תזרים כספי", icon: ArrowLeftRight, primary: true, Component: Cashflow },
  { path: "/summary", label: "סיכום התוכנית", icon: ClipboardList, Component: Summary },
  { path: "/goals", label: "יעדים", icon: Target, primary: true, Component: Goals },
  { path: "/recommendations", label: "המלצות", icon: Lightbulb, Component: Recommendations },
  { path: "/networth", label: "שווי נקי", icon: Landmark, primary: true, Component: Networth },
  { path: "/portfolio", label: "השקעות", icon: PieChart, Component: Portfolio },
  { path: "/metrics", label: "התקדמות", icon: Gauge, Component: Metrics },
  { path: "/timeline", label: "ציר זמן", icon: CalendarRange, Component: Timeline },
  { path: "/my-plan", label: "תכנון פלוס", icon: Sparkles, Component: MyPlan },
];
