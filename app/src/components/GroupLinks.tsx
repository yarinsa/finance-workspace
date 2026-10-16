import { Link } from "react-router-dom";
import { ChevronLeft } from "lucide-react";
import { routes, type RouteGroup } from "@/routes";
import { Card } from "@/components/common";

/** Link list of a hub's child pages (everything in the group except the hub itself). */
export default function GroupLinks({ group, exclude = [] }: { group: RouteGroup; exclude?: string[] }) {
  const items = routes.filter((r) => r.group === group && !r.hub && !exclude.includes(r.path));
  if (!items.length) return null;
  return (
    <Card className="!p-0">
      {items.map(({ path, label, icon: Icon }) => (
        <Link
          key={path}
          to={path}
          className="flex items-center gap-3 border-b border-line px-4 py-3 last:border-b-0 active:bg-panel-2"
        >
          <Icon className="size-5 text-muted-foreground" />
          <span className="flex-1 font-semibold">{label}</span>
          <ChevronLeft className="size-4 text-muted-foreground" />
        </Link>
      ))}
    </Card>
  );
}
