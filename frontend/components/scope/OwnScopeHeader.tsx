'use client';

import { useEffect, useState } from 'react';
import { readNetworkList } from '@/lib/network/browser';
import { ScopeHeader } from './ScopeHeader';

// The scope header on the organisation's own pages (docs/design/network-ui.md section 3): it says "Showing:
// Our organisation" at once, and offers the switch to the network variant of the page only when the
// viewer's organisation is in a network. The read of the networks never holds the page up and never breaks
// it: when it fails there is the label and no switch.

export function OwnScopeHeader({ ownHref, networkHref }: { ownHref: string; networkHref: string }) {
  const [inNetwork, setInNetwork] = useState(false);

  useEffect(() => {
    let current = true;
    void readNetworkList().then((result) => {
      if (current) setInNetwork(result.ok && result.data.networks.length > 0);
    });
    return () => {
      current = false;
    };
  }, []);

  return <ScopeHeader scope="own" switchTo={inNetwork ? { ownHref, networkHref } : undefined} />;
}
