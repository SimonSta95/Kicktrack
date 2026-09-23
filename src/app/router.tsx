import { Navigate, createHashRouter } from "react-router-dom";
import { AppShell } from "@/components/layout/AppShell";
import { LoginPage } from "@/features/auth/LoginPage";
import { ProtectedRoute } from "@/features/auth/ProtectedRoute";
import { AppRouteError } from "./AppRouteError";

const protectedShell = (
  <ProtectedRoute>
    <AppShell />
  </ProtectedRoute>
);

export const router = createHashRouter([
  { path: "/", element: protectedShell, errorElement: <AppRouteError /> },
  { path: "/squad", element: protectedShell, errorElement: <AppRouteError /> },
  { path: "/league", element: protectedShell, errorElement: <AppRouteError /> },
  { path: "/market", element: protectedShell, errorElement: <AppRouteError /> },
  { path: "/login", element: <LoginPage />, errorElement: <AppRouteError /> },
  { path: "*", element: <Navigate to="/" replace /> },
]);
