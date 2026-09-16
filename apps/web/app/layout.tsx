import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { TooltipProvider } from "@/components/ui/tooltip";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  metadataBase: new URL("https://casepilot-aicasegen.ruzhanzou.chatgpt.site"),
  title: "CasePilot — AI Test Case Workspace",
  description: "Manage structured test cases and QA execution results in your local quality workspace.",
  openGraph: {
    title: "CasePilot — AI Test Case Workspace",
    description: "Manage structured test cases and QA execution results in your local quality workspace.",
    images: [{ url: "/og.png", width: 1664, height: 936, alt: "CasePilot product preview" }],
  },
  twitter: {
    card: "summary_large_image",
    title: "CasePilot — AI Test Case Workspace",
    description: "Manage structured test cases and QA execution results in your local quality workspace.",
    images: ["/og.png"],
  },
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable}`}>
      <body className="antialiased">
        <TooltipProvider>{children}</TooltipProvider>
      </body>
    </html>
  );
}
