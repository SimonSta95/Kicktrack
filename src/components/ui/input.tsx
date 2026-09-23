import type { InputHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        "h-12 w-full rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 text-sm text-[var(--kb-white)] outline-none transition placeholder:text-[var(--kb-grey)] hover:border-[var(--border-strong)] focus:border-[var(--kb-live-red)] focus:ring-2 focus:ring-[var(--focus-ring)]",
        className,
      )}
      {...props}
    />
  );
}
