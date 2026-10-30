// The wall board as the front end reads it: the back end's `$board` Parameters
// (docs/spec/contracts.md, "HTTP surface") parsed into plain data. Times stay as
// ISO 8601 strings, exactly as the back end sent them (UTC, with a Z).

export type BoardStatus =
  | 'accepting'
  | 'limited'
  | 'not-accepting'
  | 'over-capacity'
  | 'not-updated'
  | 'out-of-hours';

export type BoardEntry = {
  serviceId: string;
  name: string;
  /** A service category code such as `urgent-community-response`. */
  category: string;
  status: BoardStatus;
  effectiveAvailable: number | null;
  overBy: number | null;
  used: number | null;
  established: number;
  pending: number;
  unitLabel: string;
  /** Null when the back end sent no comment (it leaves out an empty one, DEC-145 item 3). */
  comment: string | null;
  reportedAt: string | null;
  nextDueAt: string | null;
  wasDueAt: string | null;
};

export type Board = {
  /** In the order the back end sent them. The page never re-sorts. */
  entries: BoardEntry[];
  pressure: string;
  allLimitedOrWorse: boolean;
  /** The back end's clock when it built the board. The page's "now". */
  generatedAt: string;
  /**
   * The display name of the organisation whose board this is, from the optional
   * top-level `organisation` part (DEC-151 item 3). Null when the back end sends none.
   */
  organisation: string | null;
  /**
   * The duty coordinator's number, from the optional top-level `coordinationPhone` part (DEC-777). Null
   * or absent when the tenant has none: no number is made up.
   */
  coordinationPhone?: string | null;
};

export { parseBoardParameters, BoardParseError } from './parse';
