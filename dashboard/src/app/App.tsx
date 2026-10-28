import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Link, Route, Routes } from "react-router";

import { HistoryPage } from "../pages/HistoryPage";
import { RunPage } from "../pages/RunPage";
import { TickerPage } from "../pages/TickerPage";
import { WorkspacePage } from "../pages/WorkspacePage";
import { Shell } from "./Shell";

const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false, staleTime: 5_000 } },
});

function NotFound() {
  return <div className="page"><h1>Not found</h1><Link to="/">Back to the workspace</Link></div>;
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route element={<Shell />}>
            <Route index element={<WorkspacePage />} />
            <Route path="history" element={<HistoryPage />} />
            <Route path="runs/:runId" element={<RunPage />} />
            <Route path="ticker" element={<TickerPage />} />
            <Route path="ticker/:ticker" element={<TickerPage />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
