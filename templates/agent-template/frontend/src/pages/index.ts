import Dashboard from "./Dashboard";
import FlowChart from "./FlowChart";
import type { ComponentType } from "react";

/**
 * Page registry — nav + routing for the dashboard.
 *
 * To ADD a page (the standard flow when the user asks for one):
 *   1. Create src/pages/MyPage.tsx (default-export a component)
 *   2. Add an entry below: { name: "my-page", label: "My Page", component: MyPage }
 * The nav picks it up automatically.
 */
export interface AgentPage {
  name: string;
  label: string;
  component: ComponentType;
}

export const PAGES: AgentPage[] = [
  { name: "dashboard", label: "Dashboard", component: Dashboard },
  { name: "flow", label: "Flow", component: FlowChart },
];
