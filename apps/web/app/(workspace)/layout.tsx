"use client";

import { AuthenticatedApp } from "@/components/authenticated-app";
import { parseCasePilotRoute } from "@/lib/casepilot-route";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

export default function WorkspaceLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  // Keep authentication and workspace state above the changing catch-all segment.
  const route = parseCasePilotRoute(pathname.split("/").filter(Boolean));

  return (
    <>
      <AuthenticatedApp route={route} />
      {children}
    </>
  );
}
