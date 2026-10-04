import { NavLink } from "react-router-dom";
import { LayoutGrid } from "lucide-react";
import { routes } from "@/routes";
import { useSidebar } from "@/components/ui/sidebar";
import { cn } from "@/lib/utils";

/**
 * Floating bottom navigation for phones: a pill of the primary routes plus a
 * detached round button that opens the sidebar sheet with everything else.
 * Hidden from `md` up, where the regular sidebar takes over.
 */
export function MobileTabBar() {
  const { setOpenMobile } = useSidebar();
  const tabs = routes.filter((r) => r.primary);

  return (
    <nav
      aria-label="ניווט ראשי"
      className="fixed inset-x-0 z-40 flex items-center justify-center gap-3 px-4 md:hidden"
      style={{ bottom: "calc(env(safe-area-inset-bottom) + 12px)" }}
    >
      <div className="flex h-16 flex-1 items-center justify-around rounded-full border bg-background/80 px-2 shadow-lg backdrop-blur-xl">
        {tabs.map(({ path, label, icon: Icon }) => (
          <NavLink
            key={path}
            to={path}
            aria-label={label}
            className={({ isActive }) =>
              cn(
                "flex size-12 items-center justify-center rounded-full transition-colors active:scale-95",
                isActive ? "text-[var(--lg-accent)]" : "text-foreground/80",
              )
            }
          >
            <Icon className="size-6" strokeWidth={2.25} />
          </NavLink>
        ))}
      </div>
      <button
        type="button"
        aria-label="עוד"
        onClick={() => setOpenMobile(true)}
        className="flex size-16 shrink-0 items-center justify-center rounded-full bg-[var(--lg-accent)] text-white shadow-lg transition-transform active:scale-95"
      >
        <LayoutGrid className="size-6" strokeWidth={2.25} />
      </button>
    </nav>
  );
}
