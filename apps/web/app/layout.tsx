import type { Metadata } from "next";
import localFont from "next/font/local";
import { DEFAULT_LOCALE, directionForLocale } from "@/lib/i18n";
import "./globals.css";
import "./monarch/design.css";
import { MonarchNavigation } from "./monarch/navigation";

const inter = localFont({ src: "./monarch/fonts/IBMPlexSans-Regular.woff2", variable: "--font-body", display: "swap" });
const display = localFont({ src: "./monarch/fonts/IBMPlexSans-SemiBold.woff2", variable: "--font-display", display: "swap" });
const siteUrl = (process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000").replace(/\/$/, "");

export const metadata: Metadata = {
  metadataBase: new URL(`${siteUrl}/`),
  title: "Elexion — G20 Election Intelligence",
  description: "Transparent G20 election forecasting from the Strategic Data Company of Ankara.",
  authors: [{ name: "Strategic Data Company of Ankara", url: "https://github.com/SDCofA" }],
  creator: "Strategic Data Company of Ankara",
  openGraph: {
    title: "Elexion — G20 Election Intelligence",
    description: "Transparent G20 election forecasting from the Strategic Data Company of Ankara.",
    images: [{ url: "brand/sdcofa-election-desk-social.png", width: 1730, height: 910 }]
  },
  twitter: {
    card: "summary_large_image",
    title: "Elexion — G20 Election Intelligence",
    description: "Transparent G20 election forecasting from the Strategic Data Company of Ankara.",
    images: ["brand/sdcofa-election-desk-social.png"]
  }
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html dir={directionForLocale(DEFAULT_LOCALE)} lang={DEFAULT_LOCALE}>
      <body className={`${inter.variable} ${display.variable} monarch-product`} data-monarch-product="election">
        <MonarchNavigation />{children}</body>
    </html>
  );
}
