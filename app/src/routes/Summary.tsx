import { Card, CardLabel, Page } from "@/components/common";
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
    <Page title="סיכום התוכנית שלי" wide>
      <Card>
        <CardLabel>המסע הפיננסי שלי</CardLabel>
        <NetWorthChart height={280} />
      </Card>
      <div className="grid grid-3">
        {sections.map((s) => (
          <Card key={s.label} to={s.route}>
            <CardLabel>{s.label}</CardLabel>
            <div className="big-num" style={{ fontSize: 18 }}>{s.status}</div>
          </Card>
        ))}
      </div>
    </Page>
  );
}
