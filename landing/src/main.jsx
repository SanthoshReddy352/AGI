import React from "react";
import { createRoot } from "react-dom/client";
import { HashRouter } from "react-router-dom";
import App from "./App.jsx";

// Vellum design system, linked in order. Single source of truth lives in
// src/styles (copied verbatim from the Vellum design system).
import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/components.css";
import "./styles/nav.css";
import "./styles/suite.css";
import "./styles/motion.css";
import "./styles/fx.css";
// Page-scoped layout for this site (landing + docs).
import "./styles/site.css";

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <HashRouter>
      <App />
    </HashRouter>
  </React.StrictMode>
);
