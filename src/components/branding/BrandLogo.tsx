import { useState } from "react";

const LOGO_PATH = "/branding/kickbase-wordmark-white.svg";

export function BrandLogo() {
  const [logoMissing, setLogoMissing] = useState(false);

  if (logoMissing) {
    return (
      <div className="font-display text-[1.45rem] font-black uppercase tracking-[-0.04em] text-[var(--kb-white)]">
        KickTrack
      </div>
    );
  }

  return (
    <img
      src={LOGO_PATH}
      alt="Kickbase"
      className="h-8 w-auto max-w-48 object-contain object-left"
      onError={() => setLogoMissing(true)}
    />
  );
}
