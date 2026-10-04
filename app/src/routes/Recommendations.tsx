import { Card, PageTitle, StubNotice } from "@/components/common";
import { snapshot, shekel } from "@/lib/data";

/** No rules engine yet (PRD 05). Surface 1–2 honest derived nudges from the
 *  snapshot, clearly labeled as heuristics. */
export default function Recommendations() {
  const nudges: string[] = [];
  const t = snapshot.totals;
  if (t.credit_card_debt > 0)
    nudges.push(`חוב כרטיסי אשראי פעיל בסך ${shekel(t.credit_card_debt)} — שקול לכסות.`);
  if (t.bank_balances_sum < t.monthly_loan_service)
    nudges.push("יתרת העו\"ש נמוכה משירות החוב החודשי — תזרים תחת לחץ.");

  return (
    <div>
      <PageTitle>המלצות</PageTitle>
      <StubNotice status="חלקי · אין עדיין מנוע המלצות">
        אין מנוע חוקים בצד שלנו. בהמשך — מנוע נדנודים מלא (PRD 05). כרגע, נדנודים
        נגזרים מה-<code>snapshot</code>:
      </StubNotice>
      <div className="grid section-gap">
        {nudges.map((n, i) => (
          <Card key={i}>⚡ {n}</Card>
        ))}
        {nudges.length === 0 && <Card>אין נדנודים כרגע.</Card>}
      </div>
    </div>
  );
}
