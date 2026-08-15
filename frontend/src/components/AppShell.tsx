import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import { clearToken } from "../api/client";
import { useMe } from "../api/hooks";
import type { CurrentUser } from "../api/types";

// UI-7: consistent top navigation and breadcrumb on every screen.

const NAV = [
  { to: "/queue", label: "Queue", roles: ["agent", "lead", "admin"] },
  { to: "/dashboard", label: "Dashboard", roles: ["lead", "admin"] },
  { to: "/admin", label: "Administration", roles: ["admin"] },
  { to: "/onboarding", label: "Onboarding", roles: ["admin"] },
];

function Breadcrumb() {
  const { pathname } = useLocation();
  const parts = pathname.split("/").filter(Boolean);
  return (
    <nav aria-label="Breadcrumb" className="border-b border-slate-200 bg-white px-6 py-2 text-xs text-slate-500">
      <ol className="flex items-center gap-2">
        <li>
          <NavLink to="/queue" className="hover:underline">
            Workspace
          </NavLink>
        </li>
        {parts.map((part, index) => (
          <li key={`${part}-${index}`} className="flex items-center gap-2">
            <span aria-hidden="true">/</span>
            <span className={index === parts.length - 1 ? "font-medium text-slate-800" : ""}>
              {part.length > 20 ? `${part.slice(0, 8)}…${part.slice(-4)}` : part}
            </span>
          </li>
        ))}
      </ol>
    </nav>
  );
}

export function AppShell() {
  const navigate = useNavigate();
  const { data: user } = useMe();
  const role = (user as CurrentUser | undefined)?.role ?? "agent";

  const signOut = () => {
    clearToken();
    navigate("/login", { replace: true });
  };

  return (
    <div className="min-h-screen">
      <a href="#main" className="skip-link">
        Skip to main content
      </a>
      <header className="bg-slate-900 text-white">
        <div className="flex items-center justify-between px-6 py-3">
          <div className="flex items-center gap-8">
            <span className="text-sm font-semibold tracking-wide">Support Triage, Agent Workspace</span>
            <nav aria-label="Main" className="flex gap-1">
              {NAV.filter((item) => item.roles.includes(role)).map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={({ isActive }) =>
                    `rounded px-3 py-1.5 text-sm ${isActive ? "bg-white text-slate-900" : "text-slate-200 hover:bg-slate-800"}`
                  }
                >
                  {item.label}
                </NavLink>
              ))}
            </nav>
          </div>
          <div className="flex items-center gap-4 text-sm">
            <span className="text-slate-300">
              {user ? `${user.username} · ${user.role}` : "…"}
            </span>
            <button type="button" onClick={signOut} className="rounded border border-slate-600 px-2 py-1 text-xs hover:bg-slate-800">
              Sign out
            </button>
          </div>
        </div>
      </header>
      <Breadcrumb />
      <main id="main" className="mx-auto max-w-[1600px] px-6 py-6">
        <Outlet />
      </main>
    </div>
  );
}
