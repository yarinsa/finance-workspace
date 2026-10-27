import { Card, CardLabel, Page } from "@/components/common";
import NetWorthChart from "@/components/NetWorthChart";
import Goals from "./Goals";
import Horizons from "./Horizons";

/** The planning screen: the financial journey, goals, and the today / near / retirement split. */
export default function Plan() {
  return (
    <Page title="יעדים ותכנון" wide>
      <Card>
        <CardLabel>המסע הפיננסי שלי</CardLabel>
        <NetWorthChart height={280} />
      </Card>
      <Goals />
      <Horizons />
    </Page>
  );
}
