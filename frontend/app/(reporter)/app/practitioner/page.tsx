import { ShiftScreen } from '@/components/practitioner/ShiftScreen';

// The practitioner's shift home (RadarPhone 1). It sits inside the installed app's scope (/app) and signs in
// as the reporter's device does: with no session, the screen sends the person to the PIN screen. The page
// reads nothing itself; the screen asks the practitioner BFF.
export const dynamic = 'force-dynamic';

export default function PractitionerPage() {
  return <ShiftScreen />;
}
