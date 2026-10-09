import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { loadData } from "@/lib/data";
import "./styles.css";

const root = createRoot(document.getElementById("root")!);

function fail(err: unknown) {
  // Never render the dashboard against empty data — ₪0 everywhere looks like a
  // real answer. Say what broke instead.
  root.render(
    <div dir="rtl" style={{ padding: "2rem", fontFamily: "system-ui", lineHeight: 1.6 }}>
      <h1 style={{ fontSize: "1.25rem", marginBottom: ".5rem" }}>לא ניתן לטעון את הנתונים</h1>
      <p style={{ color: "#64748b" }}>
        {err instanceof Error ? err.message : String(err)}
      </p>
      <p style={{ color: "#64748b", marginTop: "1rem" }}>
        הרץ <code>python3 data/digest.py</code> ואז <code>infra/deploy.sh</code>.
      </p>
    </div>
  );
}

loadData()
  .then(() => {
    root.render(
      <StrictMode>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </StrictMode>
    );
  })
  .catch(fail);
