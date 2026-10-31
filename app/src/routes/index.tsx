import type { ComponentType } from "react";
import {
  CalendarRange,
  Gauge,
  House,
  Inbox as InboxIcon,
  RefreshCw,
  CalendarCheck,
  Compass,
  Ellipsis,
  ReceiptText,
  type LucideIcon,
} from "lucide-react";
import Overview from "./Overview";
import Inbox from "./Inbox";
import Metrics from "./Metrics";
import Timeline from "./Timeline";
import Syncs from "./Syncs";
import Monthly from "./Monthly";
import Transactions from "./Transactions";
import Plan from "./Plan";

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
  { key: "monthly", label: "תנועות", icon: ReceiptText, tab: true },
  { key: "plan", label: "יעדים ותכנון", icon: Compass, tab: true },
  { key: "more", label: "עוד", icon: Ellipsis, tab: false },
];

/** Every page keeps its own path (deep links); `group` only decides where it is listed. */
export const routes: RouteDef[] = [
  {
    path: "/overview",
    label: "מבט על",
    icon: House,
    group: "overview",
    hub: true,
    Component: Overview,
  },
  {
    path: "/inbox",
    label: "אינבוקס",
    icon: InboxIcon,
    group: "overview",
    Component: Inbox,
  },

  {
    path: "/transactions",
    label: "תנועות",
    icon: ReceiptText,
    group: "monthly",
    hub: true,
    Component: Transactions,
  },
  {
    path: "/monthly",
    label: "החודש",
    icon: CalendarCheck,
    group: "monthly",
    Component: Monthly,
  },

  {
    path: "/timeline",
    label: "ציר זמן",
    icon: CalendarRange,
    group: "monthly",
    Component: Timeline,
  },
  {
    path: "/metrics",
    label: "התקדמות",
    icon: Gauge,
    group: "monthly",
    Component: Metrics,
  },

  {
    path: "/plan",
    label: "יעדים ותכנון",
    icon: Compass,
    group: "plan",
    hub: true,
    Component: Plan,
  },

  {
    path: "/syncs",
    label: "סנכרונים",
    icon: RefreshCw,
    group: "more",
    hub: true,
    Component: Syncs,
  },
];

/** Retired paths kept alive for bookmarks: `from` redirects to `to`. */
export const redirects: { from: string; to: string }[] = [
  { from: "/cashflow", to: "/monthly?view=forecast" },
  { from: "/forecast", to: "/monthly?view=forecast" },
  { from: "/runway", to: "/monthly?view=forecast" },
  { from: "/recommendations", to: "/inbox?tab=suggestions" },
  { from: "/summary", to: "/plan" },
  { from: "/goals", to: "/plan" },
  { from: "/horizons", to: "/plan" },
  { from: "/portfolio", to: "/overview?lens=savings&holdings=1" },
  { from: "/networth", to: "/overview?lens=networth" },
];

/** The group a pathname belongs to (undefined for unknown paths). */
export function groupOf(pathname: string): RouteGroup | undefined {
  return routes.find((r) => r.path === pathname)?.group;
}
