import { NetworkServicesView } from './NetworkServicesView';

// One service of the network (docs/design/network-ui.md, NetworkServiceDetail, TEN-071), as its own page
// shows it: the directory, with this service open beside it (the board NServices). The reference is the
// opaque one the back end gave the row. The open service is read only: about it, its hours, its service line
// and its current criteria. The directory and the open service are one view (NetworkServicesView), so the
// list is never shown without the service it was opened from.

export function NetworkServiceDetail({ rowRef, ownHref }: { rowRef: string; ownHref: string }) {
  return <NetworkServicesView ownHref={ownHref} selectedRef={rowRef} />;
}
