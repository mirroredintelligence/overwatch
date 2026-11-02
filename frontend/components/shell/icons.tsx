// The frame's icons: simple strokes on a 24px grid (stroke 2, round caps and joins), drawn from the design
// canvas (Rail.dc.html). They are decoration: aria-hidden, and the label next to each is the name.

export const ICON_PATHS = {
  home: 'M4 11l8-7 8 7v9H4z',
  people: 'M9 11a3.2 3.2 0 1 0 0-6.4 3.2 3.2 0 0 0 0 6.4zM3 20a6 6 0 0 1 12 0M16 5.2a3.2 3.2 0 0 1 0 6M18 20a6 6 0 0 0-3-5.2',
  mail: 'M4 5h16v14H4zM4 9l8 5 8-5',
  sliders: 'M4 7h10M18 7h2M4 17h2M10 17h10M16 4v6M8 14v6',
  db: 'M5 6c0-1.7 3.1-3 7-3s7 1.3 7 3-3.1 3-7 3-7-1.3-7-3zM5 6v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6M5 12v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6',
  send: 'M21 4L10 14M21 4l-6 17-4-7-7-4z',
  share: 'M8 12a3 3 0 1 0-6 0 3 3 0 0 0 6 0zM22 5a3 3 0 1 0-6 0 3 3 0 0 0 6 0zM22 19a3 3 0 1 0-6 0 3 3 0 0 0 6 0zM8 11l8-5M8 13l8 5',
  shield: 'M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z',
  buoy: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM5.6 5.6l3.2 3.2M15.2 15.2l3.2 3.2M18.4 5.6l-3.2 3.2M8.8 15.2l-3.2 3.2',
  building: 'M4 21V5l8-2v18M12 21V9l8 2v10M8 9h.01M8 13h.01M8 17h.01M16 14h.01M16 18h.01',
  list: 'M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01',
  help: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.4-1 .9-1 1.7M12 17h.01',
  more: 'M5 12h.01M12 12h.01M19 12h.01',
  board: 'M3 5h18v11H3zM8 21h8M12 16v5',
  pulse: 'M3 12h4l3-8 4 16 3-8h4',
  inbox: 'M3 13l3-8h12l3 8v6H3zM3 13h5l1 3h6l1-3h5',
  phone: 'M6 3h4l2 5-2.5 1.5a11 11 0 0 0 5 5L16 12l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 4 5a2 2 0 0 1 2-2z',
  checklist: 'M4 6l2 2 3-3M4 14l2 2 3-3M12 7h9M12 15h9M4 21h.01',
  userPlus: 'M10 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zM3 20a7 7 0 0 1 14 0M19 8v6M16 11h6',
  history: 'M3 12a9 9 0 1 0 3-6.7L3 8M3 3v5h5M12 7v5l3 2',
  calendar: 'M4 6h16v14H4zM4 10h16M8 3v4M16 3v4',
  bell: 'M6 17V11a6 6 0 0 1 12 0v6l2 2H4zM10 21h4',
  chart: 'M4 20V4M4 20h16M8 16v-5M12 16V8M16 16v-3',
  edit: 'M4 20h4L19 9l-4-4L4 16zM13 7l4 4',
  key: 'M8 15a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM11 12h10M18 12v4',
} as const;

export type IconName = keyof typeof ICON_PATHS;

export function Icon({ name, size = 22 }: { name: IconName; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d={ICON_PATHS[name]} />
    </svg>
  );
}
