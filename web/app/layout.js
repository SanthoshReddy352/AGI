import "./globals.css";
import { Inter, JetBrains_Mono } from "next/font/google";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
});

const mono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata = {
  metadataBase: new URL("https://friday-assistant.vercel.app"),
  title: {
    default: "FRIDAY — The local-first voice AI assistant",
    template: "%s · FRIDAY",
  },
  description:
    "FRIDAY is a local-first, voice-driven AI assistant for Linux and Windows. A deterministic intent router gives small local models the tool-routing reliability that only cloud models used to have.",
  keywords: [
    "voice assistant",
    "local-first AI",
    "local LLM",
    "offline AI assistant",
    "deterministic router",
    "intent recognition",
    "privacy AI",
  ],
  openGraph: {
    title: "FRIDAY — The local-first voice AI assistant",
    description:
      "Local reasoning, local voice, local memory. A deterministic router makes tool use reliable on small on-device models.",
    type: "website",
    siteName: "FRIDAY",
  },
  twitter: {
    card: "summary_large_image",
    title: "FRIDAY — The local-first voice AI assistant",
    description:
      "Local reasoning, local voice, local memory. A deterministic router makes tool use reliable on small on-device models.",
  },
};

export const viewport = {
  themeColor: "#05070b",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en" className={`${inter.variable} ${mono.variable}`}>
      <body className="min-h-screen font-sans antialiased selection:bg-glow-cyan/30 selection:text-white">
        {children}
      </body>
    </html>
  );
}
