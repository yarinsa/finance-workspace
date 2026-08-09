import { Card, PageTitle } from "@/components/ui";
import NetWorthChart from "@/components/NetWorthChart";

const sections: { label: string; status: string; route: string }[] = [
  { label: "התחייבויות", status: "מלא", route: "/networth" },
  { label: "נכסים", status: "חלקי", route: "/networth" },
  { label: "הכנסות", status: "חלקי", route: "/cashflow" },
  { label: "הוצאות", status: "חלקי", route: "/cashflow" },
  { label: "יעדים", status: "חסר קלט", route: "/goals" },
];

export default function Summary() {
  return (
    <div>
      <PageTitle>סיכום התוכנית שלי</PageTitle>
      <Card>
        <div className="card-title">המסע הפיננסי שלי</div>
        <NetWorthChart height={280} />
      </Card>
      <div className="grid grid-3 section-gap">
        {sections.map((s) => (
          <Card key={s.label} to={s.route}>
            <div className="card-title">{s.label}</div>
            <div className="big-num" style={{ fontSize: 18 }}>{s.status}</div>
          </Card>
        ))}
      </div>
    </div>
  );
}
