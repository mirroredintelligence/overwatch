import { searchPathwaysDx } from '@/lib/advisor/terminology';
import { answer, refuse } from '@/lib/advisor/http';
import { withBff } from '@/lib/bff/handler';

// The Pathways Dx lookup for the score picker (W12). The only input is the search text, in `q`. It
// answers a list of codes the picker can offer; a code is never typed freely in the browser.

const MIN_CHARACTERS = 2;
const MAX_CHARACTERS = 64;

const get = withBff(
  async (request, session) => {
    const text = new URL(request.url).searchParams.get('q')?.trim() ?? '';
    if (text.length < MIN_CHARACTERS || text.length > MAX_CHARACTERS) return refuse(400, 'invalid');
    return answer(await searchPathwaysDx(session.backendToken, text));
  },
  // The back end admits advisors and clinicians; the picker is on the advisor's call only (W12).
  { roles: ['advisor'] },
);

export const GET = (request: Request) => get(request, undefined);
