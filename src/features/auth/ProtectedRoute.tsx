import type { PropsWithChildren } from "react";
import { useQuery } from "@tanstack/react-query";
import { Navigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { getSessionStatus } from "./api";

export function ProtectedRoute({ children }: PropsWithChildren) {
  const sessionQuery = useQuery({
    queryKey: ["auth", "session"],
    queryFn: getSessionStatus,
    staleTime: 5_000,
  });

  if (sessionQuery.isPending) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-[var(--kb-black)] text-[var(--kb-light-grey)]">
        <div className="flex items-center gap-3 text-sm">
          <span className="loading-dot bg-[var(--kb-live-red)]" /> Session wird geprüft
        </div>
      </main>
    );
  }

  if (sessionQuery.isError) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-[var(--kb-black)] px-6 text-[var(--kb-light-grey)]">
        <div className="max-w-md rounded-lg border border-[var(--danger-border)] bg-[var(--danger-surface)] p-5 text-center">
          <p className="text-sm text-[var(--danger)]">{sessionQuery.error.message}</p>
          <Button type="button" className="mt-4" onClick={() => sessionQuery.refetch()}>
            Erneut prüfen
          </Button>
        </div>
      </main>
    );
  }

  if (!sessionQuery.data?.authenticated) {
    return <Navigate to="/login" replace />;
  }

  return children;
}
