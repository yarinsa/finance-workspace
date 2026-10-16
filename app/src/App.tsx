import { NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { groups, routes } from "./routes";
import { cashflow, daysSince } from "./lib/data";
import { displayState, headline, STATE_PILL, useSyncStatus } from "./lib/syncStatus";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  useSidebar,
} from "@/components/ui/sidebar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { TooltipProvider } from "@/components/ui/tooltip";
import { MobileTabBar } from "@/components/MobileTabBar";

/**
 * "Updated N days ago" — tap-able so the stale warning works on touch. The dot
 * also carries the live sync: pulsing while a run is active, red when a source
 * waits for a login or failed (that wins over the staleness dot).
 */
function Freshness({ days }: { days: number }) {
  const stale = days > 7;
  const live = useSyncStatus();
  const sync = headline(live);
  const liveRows = Object.entries(live?.sources ?? {}).map(([source, s]) => ({ source, s, d: displayState(s) }));
  return (
    <Popover>
      <PopoverTrigger className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
        עודכן לפני {days} ימים
        {sync === "attention" ? (
          <span className="sync-dot-attention" aria-label="הסנכרון דורש טיפול" />
        ) : sync === "running" ? (
          <span className="sync-dot-running" aria-label="סנכרון רץ" />
        ) : (
          stale && <span className="stale-dot" aria-label="נתונים ישנים" />
        )}
      </PopoverTrigger>
      <PopoverContent className="w-64 text-sm">
        {stale
          ? "הנתונים ישנים משבוע — כדאי לרענן את המקורות ולהריץ digest."
          : "הנתונים עדכניים."}
        {liveRows.map(({ source, s, d }) => (
          <div key={source} className="mt-2 flex items-center justify-between gap-2">
            <NavLink to="/syncs" className="min-w-0 truncate text-muted-foreground">
              {s.message}
            </NavLink>
            <span className={`pill ${STATE_PILL[d].cls}`}>{STATE_PILL[d].text}</span>
          </div>
        ))}
      </PopoverContent>
    </Popover>
  );
}

function AppSidebar({ days }: { days: number }) {
  const { pathname } = useLocation();
  const { setOpenMobile } = useSidebar();
  return (
    <Sidebar side="right">
      <SidebarHeader>
        <div className="px-2 py-1 text-lg font-bold">תמונת מצב</div>
      </SidebarHeader>
      <SidebarContent>
        {groups.map((g) => (
          <SidebarGroup key={g.key}>
            <SidebarGroupLabel>{g.label}</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {routes
                  .filter((r) => r.group === g.key)
                  .map(({ path, label, icon: Icon, hub }) => (
                    <SidebarMenuItem key={path} className={hub ? undefined : "ps-3"}>
                      <SidebarMenuButton asChild isActive={pathname === path}>
                        <NavLink to={path} onClick={() => setOpenMobile(false)}>
                          <Icon />
                          {label}
                        </NavLink>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  ))}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        ))}
      </SidebarContent>
      <SidebarFooter>
        <div className="px-2">
          <Freshness days={days} />
        </div>
      </SidebarFooter>
    </Sidebar>
  );
}

export default function App() {
  const { pathname } = useLocation();
  const days = daysSince(cashflow.generated_at);
  const current = routes.find((r) => r.path === pathname);
  return (
    <TooltipProvider>
      <SidebarProvider>
        <AppSidebar days={days} />
        <SidebarInset>
          <header
            className="sticky top-0 z-30 flex h-12 items-center justify-between border-b bg-background/80 px-4 backdrop-blur-xl md:hidden"
            style={{ paddingTop: "env(safe-area-inset-top)", boxSizing: "content-box" }}
          >
            <span className="font-bold">{current?.label ?? ""}</span>
            <Freshness days={days} />
          </header>
          <main className="content">
            <Routes>
              <Route path="/" element={<Navigate to="/overview" replace />} />
              {routes.map((r) => (
                <Route key={r.path} path={r.path} element={<r.Component />} />
              ))}
              <Route path="*" element={<Navigate to="/overview" replace />} />
            </Routes>
          </main>
        </SidebarInset>
        <MobileTabBar />
      </SidebarProvider>
    </TooltipProvider>
  );
}
