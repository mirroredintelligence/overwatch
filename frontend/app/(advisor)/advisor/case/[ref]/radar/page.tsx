import { redirect } from 'next/navigation';

// The Radar is no longer a view of its own: it is the "Who covers this area" layer of the Map (DEC-1372). The
// old address keeps working for bookmarks and case steps, and lands on the Map with the layer on.
export default async function CaseRadarPage({ params }: { params: Promise<{ ref: string }> }) {
  const { ref } = await params;
  redirect(`/advisor/case/${encodeURIComponent(ref)}/map?layer=coverage`);
}
