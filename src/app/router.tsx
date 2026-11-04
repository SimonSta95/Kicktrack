import { Navigate, createHashRouter } from "react-router-dom";
import { AppShell } from "@/components/layout/AppShell";
import { LoginPage } from "@/features/auth/LoginPage";
import { ProtectedRoute } from "@/features/auth/ProtectedRoute";
import { PlayerDetailProvider } from "@/features/player-detail/PlayerDetailProvider";
import { AppRouteError } from "./AppRouteError";

const protectedShell = (
  <PlayerDetailProvider>
    <ProtectedRoute>
      <AppShell />
    </ProtectedRoute>
  </PlayerDetailProvider>
);

export const router = createHashRouter([
  { path: "/", element: protectedShell, errorElement: <AppRouteError /> },
  { path: "/squad", element: protectedShell, errorElement: <AppRouteError /> },
  { path: "/league", element: protectedShell, errorElement: <AppRouteError /> },
  { path: "/market", element: protectedShell, errorElement: <AppRouteError /> },
  { path: "/fair-value", element: protectedShell, errorElement: <AppRouteError /> },
  { path: "/planner", element: protectedShell, errorElement: <AppRouteError /> },
  { path: "/live", element: protectedShell, errorElement: <AppRouteError /> },
  { path: "/players/:playerId", element: protectedShell, errorElement: <AppRouteError /> },
  { path: "/login", element: <LoginPage />, errorElement: <AppRouteError /> },
  { path: "*", element: <Navigate to="/" replace /> },
]);
