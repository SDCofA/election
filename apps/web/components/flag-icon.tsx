import Image from "next/image";

import { publicAsset } from "@/lib/public-data";

const LOCAL_FLAGS = new Set(["au", "de", "eg", "eu", "gb", "us"]);

export function FlagIcon({ code, label }: { code: string; label?: string }) {
  const normalized = code.toLowerCase();
  const useLocalAsset = LOCAL_FLAGS.has(normalized) && !(normalized === "au" && label === "Australia");
  if (!useLocalAsset) {
    const flag = /^[a-z]{2}$/.test(normalized)
      ? String.fromCodePoint(...[...normalized.toUpperCase()].map((letter) => 127397 + letter.charCodeAt(0)))
      : code.toUpperCase();
    return <span className="flag-emoji" aria-label={label ? `${label} flag` : code}>{flag}</span>;
  }
  return (
    <span className="flag-icon">
      <Image
        alt={label ? `${label} flag` : `${code.toUpperCase()} flag`}
        height={32}
        src={publicAsset(`/flags/${normalized}.svg`)}
        width={48}
      />
    </span>
  );
}
