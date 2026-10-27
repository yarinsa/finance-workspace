import { NavLink, useLocation } from "react-router-dom";
import { groupOf, groups, routes } from "@/routes";
import { useSidebar } from "@/components/ui/sidebar";
import { cn } from "@/lib/utils";

const TAB = "flex min-w-0 flex-1 flex-col items-center justify-center gap-1 py-2 text-[11px] font-medium transition-colors duration-200 active:scale-95";

/**
 * Bottom navigation for phones (Empathy-style): a cream bar of labelled tabs, the active one
 * in forest. "עוד" is a tab like the others and opens the sidebar sheet with everything else.
 * Hidden from `md` up, where the regular sidebar takes over.
 */
export function MobileTabBar() {
  const { setOpenMobile, openMobile } = useSidebar();
  const { pathname } = useLocation();
  const active = groupOf(pathname);
  const more = groups.find((g) => !g.tab);
  const tabs = groups
    .filter((g) => g.tab)
    .map((g) => ({ ...g, path: routes.find((r) => r.group === g.key && r.hub)!.path }));

  return (
    <nav
      aria-label="ניווט ראשי"
      className="tab-bar fixed inset-x-0 bottom-0 z-40 border-t border-line bg-[color-mix(in_srgb,var(--lg-bg)_92%,transparent)] backdrop-blur-xl md:hidden"
      style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
    >
      <div className="mx-auto flex h-16 max-w-md items-stretch px-2">
        {tabs.map(({ key, path, label, icon: Icon }) => {
          const on = active === key && !openMobile;
          return (
            <NavLink
              key={key}
              to={path}
              viewTransition
              aria-current={on ? "page" : undefined}
              className={cn(TAB, on ? "text-[var(--lg-primary)]" : "text-muted-foreground")}
            >
              <Icon className="size-[22px]" strokeWidth={on ? 2.25 : 1.75} />
              <span className="truncate">{label}</span>
            </NavLink>
          );
        })}
        {more && (
          <button
            type="button"
            onClick={() => setOpenMobile(true)}
            className={cn(TAB, active === "more" || openMobile ? "text-[var(--lg-primary)]" : "text-muted-foreground")}
          >
            <more.icon className="size-[22px]" strokeWidth={1.75} />
            <span>{more.label}</span>
          </button>
        )}
      </div>
    </nav>
  );
}
