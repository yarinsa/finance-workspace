import { PageTitle, StubNotice } from "@/components/ui";

export default function Portfolio() {
  return (
    <div>
      <PageTitle>השקעות</PageTitle>
      <StubNotice status="חסום · דורש מקור נתונים חדש">
        אנו אוספים יתרות בנק, כרטיסים והלוואות — אך לא החזקות פנסיה / השתלמות /
        תיקי השקעות / נדל"ן, שהן עיקר השווי הנקי. נדרש מקור חדש (סקרייפר או הזנה
        ידנית). ראו <code>docs/plangram-prd/07-portfolio.md</code>.
      </StubNotice>
    </div>
  );
}
