import { PageTitle, StubNotice } from "@/components/common";

export default function MyPlan() {
  return (
    <div>
      <PageTitle>תכנון פלוס</PageTitle>
      <StubNotice status="נעול · Plus">
        סימולטור התרחישים (what-if) של Plangram חסום מאחורי מנוי Plus ולא נלכד.
        ראו <code>docs/plangram-prd/10-my-plan-plus.md</code>.
      </StubNotice>
    </div>
  );
}
