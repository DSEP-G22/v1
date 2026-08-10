import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import ReactDOM from "react-dom/client";
import { Navigate, RouterProvider, createBrowserRouter } from "react-router-dom";

import { getToken } from "./api/client";
import { AppShell } from "./components/AppShell";
import { ToastProvider } from "./components/Toasts";
import "./index.css";
import { AdminPage } from "./pages/AdminPage";
import { DashboardPage } from "./pages/DashboardPage";
import { LoginPage } from "./pages/LoginPage";
import { OnboardingPage } from "./pages/OnboardingPage";
import { QueuePage } from "./pages/QueuePage";
import { TicketPage } from "./pages/TicketPage";

function RequireAuth({ children }: { children: React.ReactNode }) {
  if (!getToken()) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

const router = createBrowserRouter(
  [
    { path: "/login", element: <LoginPage /> },
    {
      path: "/",
      element: (
        <RequireAuth>
          <AppShell />
        </RequireAuth>
      ),
      children: [
        { index: true, element: <Navigate to="/queue" replace /> },
        { path: "queue", element: <QueuePage /> },
        { path: "tickets/:ticketId", element: <TicketPage /> },
        { path: "dashboard", element: <DashboardPage /> },
        { path: "admin", element: <AdminPage /> },
        { path: "onboarding", element: <OnboardingPage /> },
      ],
    },
  ],
);

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 5_000, refetchOnWindowFocus: false, retry: 1 },
  },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <RouterProvider router={router} />
      </ToastProvider>
    </QueryClientProvider>
  </React.StrictMode>,
);
