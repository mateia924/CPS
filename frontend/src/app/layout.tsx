import type { Metadata } from "next";
import { IBM_Plex_Sans_Arabic, Tajawal } from "next/font/google";
import { AuthProvider } from "@/lib/auth-context";
import { LocaleProvider } from "@/lib/i18n";
import "./globals.css";

// BRAND.md §3: Tajawal for headings/large numbers, IBM Plex Sans Arabic
// for body/forms/tables — bundled at build time via next/font/google
// (self-hosted by Next.js, no runtime request to Google), bound to the
// --font-display/--font-body variables tokens.css already expects.
const tajawal = Tajawal({
  subsets: ["arabic", "latin"],
  weight: ["500", "700", "800"],
  display: "swap",
  variable: "--font-display",
});

const ibmPlexSansArabic = IBM_Plex_Sans_Arabic({
  subsets: ["arabic", "latin"],
  weight: ["400", "500", "600"],
  display: "swap",
  variable: "--font-body",
});

export const metadata: Metadata = {
  title: "CPS",
  description: "CPS business platform",
  icons: {
    icon: [
      { url: "/brand/cps-app-icon-32.png", sizes: "32x32" },
      { url: "/brand/cps-app-icon-192.png", sizes: "192x192" },
    ],
    apple: "/brand/cps-app-icon-180.png",
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ar" dir="rtl" className={`${tajawal.variable} ${ibmPlexSansArabic.variable}`}>
      <body>
        <LocaleProvider>
          <AuthProvider>{children}</AuthProvider>
        </LocaleProvider>
      </body>
    </html>
  );
}
