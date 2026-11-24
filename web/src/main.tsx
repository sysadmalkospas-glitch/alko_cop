import "@mantine/core/styles.css";
import "./styles.css";
import { createTheme, MantineProvider } from "@mantine/core";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { App } from "./App";

const theme = createTheme({
  primaryColor: "pine",
  primaryShade: 7,
  defaultRadius: "md",
  fontFamily: "Inter, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
  colors: {
    pine: ["#e9f5f1", "#d5eae2", "#aed5c6", "#83bfaa", "#5ba991", "#409278", "#2e7d66", "#226b56", "#195644", "#124336"],
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <MantineProvider theme={theme} forceColorScheme="light">
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </MantineProvider>
  </StrictMode>,
);
