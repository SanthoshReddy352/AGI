import { useEffect } from "react";
import { Routes, Route, useLocation } from "react-router-dom";
import { useVellum } from "./vellum/useVellum.js";
import Landing from "./pages/Landing.jsx";
import Docs from "./pages/Docs.jsx";

export default function App() {
  const { pathname } = useLocation();

  // New route: start at the top, then wire up the Vellum runtime for the
  // freshly rendered DOM (keyed on pathname so observers/listeners reset).
  useEffect(() => { window.scrollTo(0, 0); }, [pathname]);
  useVellum(pathname);

  return (
    <>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/docs" element={<Docs />} />
      </Routes>
      <div className="toast-stack" aria-live="polite"></div>
    </>
  );
}
