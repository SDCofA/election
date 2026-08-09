import type { Metadata } from "next";
import { Inter, Space_Grotesk } from "next/font/google";
import { DEFAULT_LOCALE, directionForLocale } from "@/lib/i18n";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-body" });
const display = Space_Grotesk({ subsets: ["latin"], variable: "--font-display" });

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000"),
  title: "SDCofA Election Desk — Global Election Intelligence",
  description: "Transparent, calibrated election forecasting from the Strategic Data Company of Ankara.",
  authors: [{ name: "Strategic Data Company of Ankara", url: "https://github.com/SDCofA" }],
  creator: "Strategic Data Company of Ankara",
  openGraph: {
    title: "SDCofA Election Desk — Global Election Intelligence",
    description: "Transparent, calibrated election forecasting from the Strategic Data Company of Ankara.",
    images: [{ url: "/brand/sdcofa-election-desk-social.png", width: 1730, height: 910 }]
  },
  twitter: {
    card: "summary_large_image",
    title: "SDCofA Election Desk — Global Election Intelligence",
    description: "Transparent, calibrated election forecasting from the Strategic Data Company of Ankara.",
    images: ["/brand/sdcofa-election-desk-social.png"]
  }
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html dir={directionForLocale(DEFAULT_LOCALE)} lang={DEFAULT_LOCALE}>
      <body className={`${inter.variable} ${display.variable}`}>{children}</body>
    </html>
  );
}
