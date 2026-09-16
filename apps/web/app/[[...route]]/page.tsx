import { AuthenticatedApp } from "@/components/authenticated-app";
import { parseCasePilotRoute } from "@/lib/casepilot-route";

type CasePilotPageProps = {
  params: Promise<{ route?: string[] }>;
};

export default async function CasePilotPage({ params }: CasePilotPageProps) {
  const { route } = await params;
  return <AuthenticatedApp route={parseCasePilotRoute(route)} />;
}
