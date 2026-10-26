import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import "./index.css";
import "./styles.css";
import { initPwa } from "./lib/pwa";

initPwa();

const root = createRoot(document.getElementById("root")!);

function fail(err: unknown) {
  const expired = err instanceof Error && err.name === "SessionExpiredError";
  // Never render the dashboard against empty data — ₪0 everywhere looks like a
  // real answer. Say what broke instead.
  root.render(
    <div dir="rtl" style={{ padding: "2rem", fontFamily: "system-ui", lineHeight: 1.6 }}>
      <h1 style={{ fontSize: "1.25rem", marginBottom: ".5rem" }}>לא ניתן לטעון את הנתונים</h1>
      <p style={{ color: "#64748b" }}>{err instanceof Error ? err.message : String(err)}</p>
      {expired ? (
        // The cookie lapsed: a full navigation lets the edge send us through the login again.
        <button
          type="button"
          onClick={() => location.assign("/?login=1")}
          style={{ marginTop: "1rem", padding: ".6rem 1.2rem", borderRadius: 999, border: 0, background: "#14b48c", color: "#fff", fontSize: "1rem", fontWeight: 700 }}
        >
          התחבר מחדש
        </button>
      ) : (
        <p style={{ color: "#64748b", marginTop: "1rem" }}>
          הרץ <code>python3 data/digest.py</code> ואז <code>infra/deploy.sh --data-only</code>.
        </p>
      )}
    </div>
  );
}

// App is imported dynamically because lib/data.ts fetches the digested JSON
// with top-level await: if that fetch fails, this import rejects and we can
// show why, instead of a blank page.
import("./App")
  .then(({ default: App }) =>
    root.render(
      <StrictMode>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </StrictMode>
    )
  )
  .catch(fail);
