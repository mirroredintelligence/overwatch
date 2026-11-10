'use client';

import { useEffect } from 'react';
import { ServiceDetail } from '@/components/service/ServiceDetail';
import type { DialogContext } from '@/lib/workspace/dialog';
import { workspaceHref } from '@/lib/workspace/url';
import { WorkspacePage } from './WorkspacePage';
import { useWorkspace } from './WorkspaceProvider';

// The service page inside the workspace (DEC-1376, WS-SVC): the frame around the existing service detail, and the
// assistant's turn for the service. The effect depends only on primitives, so a re-render never revisits the turn.
// Note: the service turn fills its echo ("Open {serviceName}") before choosing a reply, so a visit with an empty
// context throws when the thread already has entries. This page only visits empty when nothing is opened.

export function ServiceWorkspace({ serviceId }: { serviceId: string }) {
  const { opened, visit } = useWorkspace();
  const isOpen = opened !== null;
  const serviceName = opened?.serviceName;
  const updated = opened?.updated;
  const stale = opened?.stale;
  const noReport = opened?.noReport;

  useEffect(() => {
    const context: DialogContext = isOpen ? { serviceName, updated, stale, noReport } : {};
    visit('advisor.service', context);
  }, [visit, isOpen, serviceName, updated, stale, noReport]);

  const backHref = workspaceHref('advisor.results');
  return (
    <WorkspacePage title="Service detail" backHref={backHref} withThread>
      <ServiceDetail serviceId={serviceId} backHref={backHref} backLabel="Back to results" rootLabel="Find a service" />
    </WorkspacePage>
  );
}
