import React from "react";
import ReactDOM from "react-dom/client";

import App from "./App";
import "./styles.css";

const favicon = document.createElement("link");
favicon.rel = "icon";
favicon.href =
  "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Crect width='16' height='16' rx='3' fill='%23184b8f'/%3E%3Cpath d='M4 9.5 7 12l5-8' fill='none' stroke='white' stroke-width='2'/%3E%3C/svg%3E";
document.head.appendChild(favicon);

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
