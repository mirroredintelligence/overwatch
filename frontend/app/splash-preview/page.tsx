import { notFound } from 'next/navigation';
import { SplashPreview } from './SplashPreview';

// Development preview only: the splash is not wired into the app layout yet.
export default function SplashPreviewPage() {
  if (process.env.NODE_ENV === 'production') {
    notFound();
  }
  return <SplashPreview />;
}
