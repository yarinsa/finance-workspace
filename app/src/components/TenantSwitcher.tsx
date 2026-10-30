import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";
import { request } from "@/lib/api";
import { activeTenantId, clearTenant, currentTenant, switchTenant, type Me } from "@/lib/tenant";

/**
 * Which household's data the app shows. Renders nothing for a user with one tenant (nothing to
 * choose, and no `X-Tenant-Id` is sent). Choosing reloads the page (lib/tenant.ts), so no data of
 * the previous tenant stays in memory.
 */
export function TenantSwitcher() {
  const [me, setMe] = useState<Me | null>(null);

  useEffect(() => {
    let live = true;
    request<Me>("GET", "/me")
      .then((m) => {
        if (!live) return;
        // a remembered tenant the user no longer belongs to (removed, or suspended): forget it
        if (activeTenantId() && !m.tenants.some((t) => t.id === activeTenantId())) clearTenant();
        setMe(m);
      })
      .catch(() => {}); // offline or signed out: the app already shows that; no switcher
    return () => {
      live = false;
    };
  }, []);

  if (!me) return null;
  // the registry screen, for the platform admin only (the API enforces it too)
  const admin = me.platform_admin && (
    <NavLink to="/tenants" className="px-2 pb-1 text-xs text-muted-foreground underline-offset-2 hover:underline">
      ניהול משקי בית
    </NavLink>
  );
  if (me.tenants.length < 2) return <>{admin}</>;
  const current = currentTenant(me);
  return (
    <>
    {admin}
    <label className="flex items-center gap-2 px-2 pb-1 text-xs text-muted-foreground">
      <span>משק בית</span>
      <select
        className="min-w-0 flex-1 rounded-md border bg-background px-2 py-1 text-sm text-foreground"
        value={current?.id}
        onChange={(e) => switchTenant(e.target.value)}
      >
        {me.tenants.map((t) => (
          <option key={t.id} value={t.id}>
            {t.name}
          </option>
        ))}
      </select>
    </label>
    </>
  );
}
