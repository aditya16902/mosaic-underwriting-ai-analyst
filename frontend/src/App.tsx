import { useEffect, useState } from "react";
import { BrowserRouter, Routes, Route, useParams, Navigate } from "react-router-dom";
import { Sidebar } from "./components/layout/Sidebar";
import { ResizableChatPanel, ChatPanelToggle } from "./components/layout/ResizableChatPanel";
import { ChatPanelContent } from "./components/chat/ChatPanelContent";
import { useResizablePanel } from "./components/layout/useResizablePanel";
import { hasValidSession } from "./lib/auth";
import { LoginPage } from "./pages/LoginPage";
import { DashboardPage } from "./pages/DashboardPage";
import { SettingsPage } from "./pages/SettingsPage";
import { GenerateReportModal } from "./components/generate/GenerateReportModal";

function AppShell({ onLogout }: { onLogout: () => void }) {
  const chatPanel = useResizablePanel();
  const [generateOpen, setGenerateOpen] = useState(false);

  return (
    <div className="h-screen w-screen flex overflow-hidden bg-page">
      <Sidebar onGenerateClick={() => setGenerateOpen(true)} onLogout={onLogout} />

      <main className="flex-1 overflow-y-auto">
        <Routes>
          <Route path="/" element={<RedirectToLatestOrEmpty />} />
          <Route path="/reports/:runId" element={<RoutedDashboard />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </main>

      <ResizableChatPanel panelState={chatPanel}>
        <RoutedChatContent />
      </ResizableChatPanel>

      {!chatPanel.isOpen && <ChatPanelToggle onOpen={chatPanel.open} />}

      {generateOpen && <GenerateReportModal onClose={() => setGenerateOpen(false)} />}
    </div>
  );
}

/** Renders the dashboard for whichever run_id is in the URL. */
function RoutedDashboard() {
  const { runId } = useParams<{ runId: string }>();
  if (!runId) return null;
  return <DashboardPage runId={runId} />;
}

/** Chat panel is always scoped to whatever report is currently on screen. */
function RoutedChatContent() {
  const { runId } = useParams<{ runId: string }>();
  return <ChatPanelContent runId={runId ?? null} />;
}

/** Landing at "/" sends the user to the most recent report, if any exist. */
function RedirectToLatestOrEmpty() {
  const [latestRunId, setLatestRunId] = useState<string | null | undefined>(undefined);

  useEffect(() => {
    import("./lib/api").then(({ api }) => {
      api
        .get<{ run_id: string }[]>("/reports")
        .then((reports) => setLatestRunId(reports[0]?.run_id ?? null))
        .catch(() => setLatestRunId(null));
    });
  }, []);

  if (latestRunId === undefined) return null; // loading
  if (latestRunId === null) {
    return (
      <div className="h-full flex items-center justify-center px-8">
        <div className="text-center max-w-sm">
          <h2 className="font-display text-2xl text-ink mb-2">No reports yet</h2>
          <p className="text-sm text-warmgray leading-relaxed">
            Generate the first weekly report from the sidebar to see the dashboard,
            narrative, and signal detail here.
          </p>
        </div>
      </div>
    );
  }
  return <Navigate to={`/reports/${latestRunId}`} replace />;
}

export default function App() {
  const [authed, setAuthed] = useState<boolean | undefined>(undefined);

  useEffect(() => {
    hasValidSession().then(setAuthed);
  }, []);

  if (authed === undefined) return null; // checking cached token

  if (!authed) {
    return <LoginPage onLoginSuccess={() => setAuthed(true)} />;
  }

  return (
    <BrowserRouter>
      <AppShell onLogout={() => setAuthed(false)} />
    </BrowserRouter>
  );
}
