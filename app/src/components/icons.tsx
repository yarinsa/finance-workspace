/** Inline stroke icons for the tab bar — no icon package, currentColor themed. */
const base = {
  width: 22,
  height: 22,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.8,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
};

export const HomeIcon = () => (
  <svg {...base}><path d="M3 10.5 12 3l9 7.5" /><path d="M5 9.5V20h14V9.5" /><path d="M10 20v-5h4v5" /></svg>
);
export const CashflowIcon = () => (
  <svg {...base}><path d="M4 20V11" /><path d="M10 20V5" /><path d="M16 20v-7" /><path d="M21 20H3" /></svg>
);
export const GoalIcon = () => (
  <svg {...base}><circle cx="12" cy="12" r="8.5" /><circle cx="12" cy="12" r="4.5" /><circle cx="12" cy="12" r="1" /></svg>
);
export const WalletIcon = () => (
  <svg {...base}><rect x="3" y="6" width="18" height="13" rx="3" /><path d="M3 10h18" /><path d="M16 14.5h2" /></svg>
);
export const MoreIcon = () => (
  <svg {...base}><circle cx="5" cy="12" r="1.3" /><circle cx="12" cy="12" r="1.3" /><circle cx="19" cy="12" r="1.3" /></svg>
);
