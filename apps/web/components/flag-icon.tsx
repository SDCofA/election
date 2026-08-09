import Image from "next/image";

import { publicAsset } from "@/lib/public-data";

const LOCAL_FLAGS = new Set(["au", "de", "eg", "eu", "gb", "us"]);

export function FlagIcon({ code, label }: { code: string; label?: string }) {
  const normalized = code.toLowerCase();
  if (!LOCAL_FLAGS.has(normalized)) {
    return <span className="flag-code" aria-label={label ?? code}>{code.toUpperCase()}</span>;
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
