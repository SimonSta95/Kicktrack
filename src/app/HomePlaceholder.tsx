import { LogOut } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { BrandLogo } from "@/components/branding/BrandLogo";
import { Button } from "@/components/ui/button";
import { logout } from "@/features/auth/api";

export function HomePlaceholder() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  async function handleLogout() {
    await logout();
    queryClient.setQueryData(["auth", "session"], {
      authenticated: false,
      tokenExpiresAt: null,
      remembered: false,
    });
    navigate("/login", { replace: true });
  }

  return (
    <main className="min-h-screen bg-[var(--kb-black)] p-8 text-[var(--kb-white)]">
      <div className="mx-auto flex max-w-6xl items-center justify-between border-b border-[var(--border)] pb-6">
        <BrandLogo />
        <Button variant="ghost" onClick={handleLogout}>
          <LogOut size={17} /> Abmelden
        </Button>
      </div>
      <section className="mx-auto max-w-6xl py-20">
        <p className="mb-3 text-xs font-bold uppercase tracking-[0.2em] text-[var(--kb-live-red)]">Session aktiv</p>
        <h1 className="font-display text-5xl font-black uppercase tracking-[-0.04em]">Kickbase verbunden.</h1>
        <p className="mt-5 max-w-2xl text-base leading-7 text-[var(--kb-light-grey)]">
          Der Login-Slice steht. Als nächstes kommt der Account-/Liga-Bootstrap mit Liga-Auswahl, Budget und Kadergrenzen.
        </p>
      </section>
    </main>
  );
}
