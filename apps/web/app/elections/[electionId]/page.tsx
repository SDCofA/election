import { ForecastDashboard } from "@/components/forecast-dashboard";
import elections from "@/public/data/v1/elections.json";

export function generateStaticParams() {
  return elections.map((election) => ({ electionId: election.id }));
}

export default async function ElectionPage({
  params
}: {
  params: Promise<{ electionId: string }>;
}) {
  const { electionId } = await params;
  return <ForecastDashboard electionId={electionId} />;
}
