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
  title: "CasePilot — AI 测试设计工作台",
  description: "从需求文档到可评审测试用例、脑图与结构化测试说明。",
  openGraph: {
    title: "CasePilot — AI 测试设计工作台",
    description: "从需求文档到可评审测试用例、脑图与结构化测试说明。",
    images: [{ url: "/og.png", width: 1664, height: 936, alt: "CasePilot 蓝白主题产品预览" }],
  },
  twitter: {
    card: "summary_large_image",
    title: "CasePilot — AI 测试设计工作台",
    description: "从需求文档到可评审测试用例、脑图与结构化测试说明。",
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
    <html lang="zh-CN" className={`${geistSans.variable} ${geistMono.variable}`}>
      <body className="antialiased">
        <TooltipProvider>{children}</TooltipProvider>
      </body>
    </html>
  );
}
