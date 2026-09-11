import { redirect } from "next/navigation";

type CaseProjectPageProps = {
  params: Promise<{ caseProjectId: string }>;
  searchParams: Promise<{ access_token?: string }>;
};

export default async function CaseProjectPage({
  params,
  searchParams,
}: CaseProjectPageProps) {
  const { caseProjectId } = await params;
  const { access_token: accessToken } = await searchParams;
  const query = new URLSearchParams({ case_project_id: caseProjectId });
  if (accessToken) query.set("access_token", accessToken);
  redirect(`/?${query.toString()}`);
}
