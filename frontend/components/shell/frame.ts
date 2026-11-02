// What the frame's pieces share: the shape of a rail item, and the rule for which item is the current page.
// Plain data and functions only, so a server component can build the items and hand them to the frame.

import type { IconName } from './icons';

export type FramePortal = 'staff' | 'tenant' | 'network' | 'operator';

export type FrameItem = {
  /** The visible word under the icon, and the link's name. */
  readonly label: string;
  readonly href: string;
  readonly icon: IconName;
  /** True for a portal's home: it is current on its own page only, not on the pages below it. */
  readonly exact?: boolean;
  /** Other paths this item stands for (a detail page that has no item of its own). */
  readonly alsoMatch?: readonly string[];
};

export type Crumb = { readonly label: string; readonly href?: string };

const bare = (path: string): string => (path.length > 1 && path.endsWith('/') ? path.slice(0, -1) : path);
const within = (path: string, base: string): boolean => path === base || path.startsWith(`${base}/`);

/** Whether `item` is the page the person is on (or one of its own sub-pages). */
export function itemIsCurrent(pathname: string, item: FrameItem): boolean {
  const path = bare(pathname);
  const own = item.exact ? path === bare(item.href) : within(path, bare(item.href));
  return own || (item.alsoMatch ?? []).some((base) => within(path, bare(base)));
}
