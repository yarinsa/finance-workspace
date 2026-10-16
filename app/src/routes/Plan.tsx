import { Card, CardLabel, PageTitle, Section } from "@/components/common";
import GroupLinks from "@/components/GroupLinks";
import { goals } from "@/lib/data";

/** Planning hub: a glance at personal goals, then links to the rest of the planning pages. */
export default function Plan() {
  const personal = goals.personal_goals ?? [];
  return (
    <div className="feed">
      <PageTitle>יעדים ותכנון</PageTitle>
      {personal.length > 0 && (
        <Section title="יעדים" to="/goals">
          <Card to="/goals">
            <CardLabel>{personal.length} יעדים אישיים</CardLabel>
            {personal.slice(0, 3).map((g, i) => (
              <div key={g.id ?? i} className="flex items-center justify-between gap-3 py-1.5">
                <span className="truncate">{g.description}</span>
                <strong className="tabular-nums">{Math.round(g.progress_pct ?? 0)}%</strong>
              </div>
            ))}
          </Card>
        </Section>
      )}
      <GroupLinks group="plan" />
    </div>
  );
}
