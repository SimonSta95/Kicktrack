import { FormEvent, useState } from "react";
import { ArrowRight, Check, Eye, EyeOff, LockKeyhole, WifiOff } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { BrandLogo } from "@/components/branding/BrandLogo";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { login } from "./api";

export function LoginPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [remember, setRemember] = useState(true);

  const loginMutation = useMutation({
    mutationFn: () => login(email.trim(), password, remember),
    onSuccess: (session) => {
      queryClient.setQueryData(["auth", "session"], session);
      navigate("/", { replace: true });
    },
  });

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!email.trim() || !password || loginMutation.isPending) return;
    loginMutation.mutate();
  }

  return (
    <main className="login-shell min-h-screen bg-[var(--kb-black)] text-[var(--kb-white)]">
      <section className="login-brand-panel relative hidden overflow-hidden lg:flex">
        <div className="dot-grid absolute inset-0 opacity-45" aria-hidden="true" />
        <div className="brand-glow absolute -bottom-36 -left-24 h-96 w-96 rounded-full" aria-hidden="true" />

        <div className="relative z-10 flex h-full flex-col justify-between p-12 xl:p-16">
          <BrandLogo />

          <div className="max-w-xl pb-8">
            <p className="mb-5 text-xs font-bold uppercase tracking-[0.22em] text-[var(--kb-live-red)]">
              Companion for Kickbase
            </p>
            <h1 className="font-display text-6xl font-black uppercase leading-[0.88] tracking-[-0.045em] xl:text-7xl">
              Mehr aus deinen
              <br />
              Daten holen.
            </h1>
            <p className="mt-7 max-w-lg text-base leading-7 text-[var(--kb-light-grey)]">
              KickTrack verbindet deine Kickbase-Daten mit historischen Werten, lokalen Assets und späteren Analysen – ohne den schnellen Liga-Flow aus den Augen zu verlieren.
            </p>
          </div>

          <div className="flex items-center gap-2 text-xs text-[var(--kb-grey)]">
            <span className="h-1.5 w-1.5 rounded-full bg-[var(--kb-live-red)]" />
            Inoffizieller Desktop-Client · Kickbase API kann sich ändern
          </div>
        </div>
      </section>

      <section className="flex min-h-screen items-center justify-center px-6 py-10 sm:px-10 lg:px-14">
        <div className="w-full max-w-md">
          <div className="mb-10 lg:hidden">
            <BrandLogo />
          </div>

          <div className="mb-8">
            <p className="mb-3 text-xs font-bold uppercase tracking-[0.2em] text-[var(--kb-grey)]">KickTrack</p>
            <h2 className="font-display text-4xl font-black uppercase tracking-[-0.035em] sm:text-5xl">Anmelden</h2>
            <p className="mt-3 text-sm leading-6 text-[var(--kb-light-grey)]">
              Verwende deine normalen Kickbase-Zugangsdaten. Dein Passwort wird nicht gespeichert.
            </p>
          </div>

          <form className="space-y-5" onSubmit={handleSubmit}>
            <label className="block">
              <span className="mb-2 block text-xs font-bold uppercase tracking-[0.12em] text-[var(--kb-light-grey)]">E-Mail</span>
              <Input
                type="email"
                autoComplete="email"
                placeholder="name@beispiel.de"
                value={email}
                onChange={(event) => setEmail(event.currentTarget.value)}
                disabled={loginMutation.isPending}
              />
            </label>

            <div>
              <label className="block">
                <span className="mb-2 block text-xs font-bold uppercase tracking-[0.12em] text-[var(--kb-light-grey)]">Passwort</span>
                <div className="relative">
                  <Input
                    type={showPassword ? "text" : "password"}
                    autoComplete="current-password"
                    placeholder="••••••••••••"
                    value={password}
                    onChange={(event) => setPassword(event.currentTarget.value)}
                    disabled={loginMutation.isPending}
                    className="password-input pr-12"
                  />
                  <button
                    type="button"
                    className="absolute right-1 top-1 flex h-10 w-10 items-center justify-center rounded-md text-[var(--kb-grey)] transition hover:bg-[var(--surface-strong)] hover:text-[var(--kb-white)]"
                    onClick={() => setShowPassword((visible) => !visible)}
                    aria-label={showPassword ? "Passwort verbergen" : "Passwort anzeigen"}
                  >
                    {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                  </button>
                </div>
              </label>

              <label className="mt-3 inline-flex cursor-pointer select-none items-center gap-2.5 text-sm text-[var(--kb-light-grey)]">
                <input
                  type="checkbox"
                  className="peer sr-only"
                  checked={remember}
                  onChange={(event) => setRemember(event.currentTarget.checked)}
                  disabled={loginMutation.isPending}
                />
                <span className="flex h-4.5 w-4.5 items-center justify-center rounded border border-[var(--border-strong)] bg-[var(--surface)] transition peer-checked:border-[var(--kb-live-red)] peer-checked:bg-[var(--kb-live-red)] peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-[var(--kb-live-red)]">
                  {remember ? <Check size={13} strokeWidth={3} className="text-[var(--kb-black)]" /> : null}
                </span>
                Angemeldet bleiben
              </label>
            </div>

            {loginMutation.isError ? (
              <div className="flex gap-3 rounded-lg border border-[var(--danger-border)] bg-[var(--danger-surface)] px-4 py-3 text-sm text-[var(--danger)]">
                <WifiOff className="mt-0.5 shrink-0" size={17} />
                <span>{loginMutation.error.message}</span>
              </div>
            ) : null}

            <Button type="submit" className="w-full" disabled={!email.trim() || !password || loginMutation.isPending}>
              {loginMutation.isPending ? (
                <>
                  <span className="loading-dot" /> Verbindung wird geprüft
                </>
              ) : (
                <>
                  Anmelden <ArrowRight size={18} />
                </>
              )}
            </Button>
          </form>

          <div className="mt-7 flex items-start gap-3 rounded-lg border border-[var(--border)] bg-[var(--surface-subtle)] p-4">
            <LockKeyhole className="mt-0.5 shrink-0 text-[var(--kb-grey)]" size={17} />
            <p className="text-xs leading-5 text-[var(--kb-grey)]">
              Mit „Angemeldet bleiben“ wird nur deine Kickbase-Session sicher im Windows Credential Manager abgelegt. Dein Passwort speichert KickTrack nicht.
            </p>
          </div>
        </div>
      </section>
    </main>
  );
}
