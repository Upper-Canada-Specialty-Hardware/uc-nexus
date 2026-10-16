/**
 * What the report bubble sends about where the user was (#1677).
 *
 * Only what the browser alone knows: the page, the screen, and what had just gone wrong in this tab.
 * Who the user is never travels from here - the backend takes that from the verified session.
 */

/** The build this bundle came from, baked in by the Dockerfile from Railway's commit hash. */
export const FRONTEND_BUILD: string = (import.meta.env.VITE_BUILD_SHA || 'dev').slice(0, 12);

const ERRORS_KEPT = 10;
const ERROR_LENGTH = 1000;

const recentErrors: string[] = [];

function clip(text: string): string {
  return text.length > ERROR_LENGTH ? `${text.slice(0, ERROR_LENGTH - 1)}…` : text;
}

function describe(value: unknown): string {
  if (value instanceof Error) return value.stack || `${value.name}: ${value.message}`;
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

/** Keep one error for the next report. Oldest goes first past the last ten. */
export function recordError(...parts: unknown[]): void {
  const line = parts.map(describe).join(' ').trim();
  if (!line) return;
  recentErrors.push(`${new Date().toISOString()} ${clip(line)}`);
  if (recentErrors.length > ERRORS_KEPT) recentErrors.splice(0, recentErrors.length - ERRORS_KEPT);
}

export function readRecentErrors(): string[] {
  return [...recentErrors];
}

/** For tests. */
export function clearRecentErrors(): void {
  recentErrors.length = 0;
}

let installed = false;

/**
 * Start keeping errors: console.error (React's own and the Apollo error link's both land there), a
 * script error, and a promise nobody caught. Once per page; a second call does nothing.
 */
export function installErrorCapture(): void {
  if (installed || typeof window === 'undefined') return;
  installed = true;
  const original = console.error.bind(console);
  console.error = (...args: unknown[]) => {
    recordError(...args);
    original(...args);
  };
  window.addEventListener('error', (event) => recordError(event.error ?? event.message));
  window.addEventListener('unhandledrejection', (event) => recordError('Unhandled rejection:', event.reason));
}

export interface ReportRecord {
  name: string;
  id: string;
}

// A uuid, a number, or a document number like PO-REQ-1234 / PS-D17 / P001234.
const ID_SEGMENT = /^([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|\d+|[A-Z]{1,4}(-[A-Z]{1,4})*-?\d+)$/i;

/**
 * The records the page was showing, read off the url: each id-looking path segment named by the one
 * before it (`/app/warehouse/pull-requests/<id>/pick` → pull-requests <id>), and every query
 * parameter whose value looks like an id (`?project=<id>`).
 */
export function recordsFromLocation(pathname: string, search: string): ReportRecord[] {
  const records: ReportRecord[] = [];
  const segments = pathname.split('/').filter(Boolean);
  for (let i = 1; i < segments.length; i++) {
    const segment = decodeURIComponent(segments[i]);
    if (ID_SEGMENT.test(segment)) records.push({ name: segments[i - 1], id: segment });
  }
  new URLSearchParams(search).forEach((value, key) => {
    if (ID_SEGMENT.test(value)) records.push({ name: key, id: value });
  });
  return records.slice(0, 10);
}

/** The module the path sits in: the first segment after /app, or home. */
export function moduleFromPath(pathname: string): string {
  return pathname.replace(/^\/app\/?/, '').split('/').filter(Boolean)[0] ?? 'home';
}

/** The page's own title: the page header's heading, or the document's. */
function pageTitle(): string {
  const heading = document.querySelector('main h1, main h2, main h3, main h4, main h5');
  return heading?.textContent?.trim() || document.title;
}

export interface ReportContextInput {
  url: string;
  route: string;
  module: string;
  pageTitle: string;
  records: ReportRecord[];
  viewport: string;
  screen: string;
  colorScheme: string;
  userAgent: string;
  timezone: string;
  clientTime: string;
  build: string;
  recentErrors: string[];
}

/** Everything the report carries about the page, read the moment it is sent. */
export function collectReportContext(colorScheme: string): ReportContextInput {
  const { location } = window;
  return {
    url: location.href,
    route: location.pathname + location.search,
    module: moduleFromPath(location.pathname),
    pageTitle: pageTitle(),
    records: recordsFromLocation(location.pathname, location.search),
    viewport: `${window.innerWidth}x${window.innerHeight}`,
    screen: `${window.screen.width}x${window.screen.height} @${window.devicePixelRatio}x`,
    colorScheme,
    userAgent: navigator.userAgent,
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    clientTime: new Date().toString(),
    build: FRONTEND_BUILD,
    recentErrors: readRecentErrors(),
  };
}
