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
  title: "CasePilot — 用例管理与执行工作台",
  description: "在本地质量空间中管理结构化测试用例并记录 QA 执行结果。",
  openGraph: {
    title: "CasePilot — 用例管理与执行工作台",
    description: "在本地质量空间中管理结构化测试用例并记录 QA 执行结果。",
    images: [{ url: "/og.png", width: 1664, height: 936, alt: "CasePilot 蓝白主题产品预览" }],
  },
  twitter: {
    card: "summary_large_image",
    title: "CasePilot — 用例管理与执行工作台",
    description: "在本地质量空间中管理结构化测试用例并记录 QA 执行结果。",
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
