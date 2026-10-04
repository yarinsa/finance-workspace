import { NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { routes } from "./routes";
import { cashflow, daysSince } from "./lib/data";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar";
import { TooltipProvider } from "@/components/ui/tooltip";

export default function App() {
  const { pathname } = useLocation();
  const days = daysSince(cashflow.generated_at);
  const stale = days > 7;
  return (
    <TooltipProvider>
      <SidebarProvider>
        <Sidebar side="right">
          <SidebarHeader>
            <div className="px-2 py-1 text-lg font-bold">Plangram</div>
          </SidebarHeader>
          <SidebarContent>
            <SidebarGroup>
              <SidebarGroupContent>
                <SidebarMenu>
                  {routes.map((r) => (
                    <SidebarMenuItem key={r.path}>
                      <SidebarMenuButton asChild isActive={pathname === r.path}>
                        <NavLink to={r.path}>{r.label}</NavLink>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  ))}
                </SidebarMenu>
              </SidebarGroupContent>
            </SidebarGroup>
          </SidebarContent>
          <SidebarFooter>
            <div className="px-2 text-xs text-muted-foreground">
              עודכן לפני {days} ימים
              {stale && <span className="stale-dot" title="נתונים ישנים" />}
            </div>
          </SidebarFooter>
        </Sidebar>
        <SidebarInset>
          <header className="flex h-12 items-center gap-2 border-b px-4 md:hidden">
            <SidebarTrigger />
            <span className="font-bold">Plangram</span>
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
      </SidebarProvider>
    </TooltipProvider>
  );
}
