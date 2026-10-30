// Stub (red commit).
export type TourStep = 'welcome' | 'role' | 'changes' | 'how' | 'practice' | 'week';

export function Tour(props: { initialStep: TourStep; initialRole?: string }) {
  void props;
  return <div />;
}
