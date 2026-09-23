import type { ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost";
};

export function Button({ className, variant = "primary", ...props }: ButtonProps) {
  const variants = {
    primary:
      "bg-[var(--kb-live-red)] text-[var(--kb-black)] hover:brightness-110 focus-visible:ring-[var(--kb-live-red)]",
    secondary:
      "bg-[var(--surface-strong)] text-[var(--kb-white)] hover:bg-[var(--surface-hover)] focus-visible:ring-[var(--kb-light-grey)]",
    ghost:
      "bg-transparent text-[var(--kb-light-grey)] hover:bg-[var(--surface)] hover:text-[var(--kb-white)] focus-visible:ring-[var(--kb-light-grey)]",
  } as const;

  return (
    <button
      className={cn(
        "inline-flex h-11 items-center justify-center gap-2 rounded-lg px-4 text-sm font-semibold transition disabled:pointer-events-none disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--kb-black)]",
        variants[variant],
        className,
      )}
      {...props}
    />
  );
}
