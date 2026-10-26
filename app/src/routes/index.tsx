import type { ComponentType } from "react";
import {
  CalendarRange,
  ClipboardList,
  Gauge,
  House,
  Inbox as InboxIcon,
  Landmark,
  RefreshCw,
  PieChart,
  Sparkles,
  Target,
  CalendarCheck,
  Compass,
  Ellipsis,
  Scale,
  type LucideIcon,
  Receipt,
  Repeat,
  Wallet,
} from "lucide-react";
import Overview from "./Overview";
import Inbox from "./Inbox";
import Summary from "./Summary";
import Goals from "./Goals";
import Networth from "./Networth";
import Portfolio from "./Portfolio";
import Metrics from "./Metrics";
import Timeline from "./Timeline";
import MyPlan from "./MyPlan";
import Syncs from "./Syncs";
import Budgets from "./Budgets";
import Spending from "./Spending";
import Monthly from "./Monthly";
import Fixed from "./Fixed";
import Plan from "./Plan";
import HorizonsPage from "./Horizons";

/** Navigation hubs, Mint-style: each is one bottom tab (and one sidebar section). */
export type RouteGroup = "overview" | "monthly" | "plan" | "more";

export interface RouteDef {
  path: string;
  label: string; // Hebrew nav label
  icon: LucideIcon;
  /** Which hub the route belongs to; drives the tab bar and sidebar sections. */
  group: RouteGroup;
  /** The group's landing page — the one its bottom tab links to. */
  hub?: boolean;
  Component: ComponentType;
}

export interface GroupDef {
  key: RouteGroup;
  label: string;
  icon: LucideIcon;
  /** Pinned to the mobile tab bar; `more` lives behind the round button. */
  tab: boolean;
}

/** Group order = tab order = sidebar section order. */
export const groups: GroupDef[] = [
  { key: "overview", label: "מבט על", icon: House, tab: true },
  { key: "monthly", label: "החודש", icon: CalendarCheck, tab: true },
  { key: "plan", label: "יעדים ותכנון", icon: Compass, tab: true },
  { key: "more", label: "עוד", icon: Ellipsis, tab: false },
];

/** Every page keeps its own path (deep links); `group` only decides where it is listed. */
export const routes: RouteDef[] = [
  { path: "/overview", label: "מבט על", icon: House, group: "overview", hub: true, Component: Overview },
  { path: "/inbox", label: "אינבוקס", icon: InboxIcon, group: "overview", Component: Inbox },
  { path: "/networth", label: "שווי נקי", icon: Landmark, group: "overview", Component: Networth },

  { path: "/monthly", label: "החודש", icon: CalendarCheck, group: "monthly", hub: true, Component: Monthly },
  { path: "/budgets", label: "תקציב", icon: Wallet, group: "monthly", Component: Budgets },
  { path: "/spending", label: "הוצאות החודש", icon: Receipt, group: "monthly", Component: Spending },
  { path: "/fixed", label: "הוצאות קבועות", icon: Repeat, group: "monthly", Component: Fixed },

  { path: "/timeline", label: "ציר זמן", icon: CalendarRange, group: "monthly", Component: Timeline },
  { path: "/metrics", label: "התקדמות", icon: Gauge, group: "monthly", Component: Metrics },

  { path: "/plan", label: "יעדים ותכנון", icon: Compass, group: "plan", hub: true, Component: Plan },
  { path: "/horizons", label: "היום · קרוב · פרישה", icon: Scale, group: "plan", Component: HorizonsPage },
  { path: "/goals", label: "יעדים", icon: Target, group: "plan", Component: Goals },
  { path: "/summary", label: "סיכום התוכנית", icon: ClipboardList, group: "plan", Component: Summary },
  { path: "/my-plan", label: "תכנון פלוס", icon: Sparkles, group: "plan", Component: MyPlan },
  { path: "/portfolio", label: "השקעות", icon: PieChart, group: "plan", Component: Portfolio },

  { path: "/syncs", label: "סנכרונים", icon: RefreshCw, group: "more", hub: true, Component: Syncs },
];

/** Retired paths kept alive for bookmarks: `from` redirects to `to`. */
export const redirects: { from: string; to: string }[] = [
  { from: "/cashflow", to: "/monthly?view=forecast" },
  { from: "/forecast", to: "/monthly?view=forecast" },
  { from: "/runway", to: "/monthly?view=forecast" },
  { from: "/recommendations", to: "/inbox?tab=suggestions" },
];

/** The group a pathname belongs to (undefined for unknown paths). */
export function groupOf(pathname: string): RouteGroup | undefined {
  return routes.find((r) => r.path === pathname)?.group;
}
