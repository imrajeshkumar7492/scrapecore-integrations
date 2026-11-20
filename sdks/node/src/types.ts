export type Format = "html" | "markdown" | "text";

export interface ScrapeOptions {
  format?: Format;
  /** Run JavaScript in a real browser (more credits). */
  jsRender?: boolean;
  useProxy?: boolean;
  waf?: boolean;
  /** Seconds: a stored result at most this old is fine (faster). */
  maxAge?: number;
}

export interface ScrapeResult {
  success: boolean;
  url?: string;
  status_code?: number;
  html?: string;
  markdown?: string;
  text?: string;
  format?: Format;
  credits_used?: number;
  credits_remaining?: number;
  error?: string;
  [k: string]: unknown;
}

export interface MapOptions {
  limit?: number;
  /** Only URLs containing this text. */
  search?: string;
  includeSubdomains?: boolean;
  respectRobots?: boolean;
}

export interface MapResult {
  urls: string[];
  count: number;
  sources?: Record<string, number>;
  robots?: { respected: boolean; rules: number };
  credits_used?: number;
  [k: string]: unknown;
}

export interface CrawlOptions {
  maxDepth?: number;
  limit?: number;
  /** Regular expressions on the URL path, e.g. ["^/docs"]. */
  includePaths?: string[];
  excludePaths?: string[];
  includeSubdomains?: boolean;
  respectRobots?: boolean;
  jsRender?: boolean;
  useProxy?: boolean;
}

export interface CrawlPage {
  n: number;
  url: string;
  depth: number;
  success: boolean;
  status_code?: number;
  title?: string;
  markdown?: string;
  links_found?: number;
  error?: string | null;
}

export type JobStatus = "queued" | "running" | "retrying" | "success" | "failure" | "cancelled";

export interface Job {
  job_id: string;
  type: string;
  status: JobStatus;
  url?: string;
  progress?: number;
  credits_used?: number;
  result?: any;
  error?: string | null;
  [k: string]: unknown;
}

export interface WaitOptions {
  /** Seconds (default 300). */
  timeout?: number;
  /** Seconds between polls at first (default 1, grows to 10). */
  pollInterval?: number;
  /** Throw JobFailedError on failure/cancelled (default true). */
  throwOnFailure?: boolean;
}

export interface ScreenshotOptions {
  fullPage?: boolean;
  device?: "desktop" | "desktop_hd" | "laptop" | "tablet" | "mobile";
  width?: number;
  height?: number;
  format?: "png" | "jpeg";
  quality?: number;
  selector?: string;
  waitFor?: string;
  waitMs?: number;
  darkMode?: boolean;
  blockAds?: boolean;
  hideCookieBanners?: boolean;
  /** Wait for the job and return its result (default true). */
  wait?: boolean;
  timeout?: number;
  [k: string]: unknown;
}

export interface AiExtractOptions {
  /** What to extract, in plain words. */
  prompt?: string;
  /** JSON schema the result must match. */
  schema?: Record<string, unknown>;
  /** claude-haiku-5-5 | claude-sonnet-5-5 | claude-opus-5-5 (default: the platform default). */
  model?: string;
  jsRender?: boolean;
  useProxy?: boolean;
}

export interface AiExtractResult {
  data: any;
  model?: string;
  usage?: { input_tokens: number; output_tokens: number };
  credits_used?: number;
  [k: string]: unknown;
}

export interface SearchOptions {
  limit?: number;
  /** Scrape every result (default true). */
  scrape?: boolean;
  format?: "markdown" | "text" | "html";
  provider?: "brave" | "serper";
  maxChars?: number;
}

export interface SearchResult {
  query: string;
  results: Array<{ title: string; url: string; snippet?: string; markdown?: string; success?: boolean; [k: string]: unknown }>;
  [k: string]: unknown;
}

export type CrawlExportFormat = "jsonl" | "markdown" | "chunks" | "llms" | "llms-full";

export interface MonitorOptions {
  /** 15, 60, 360, 1440 (default) or 10080 minutes, within your plan's limit. */
  intervalMinutes?: number;
  name?: string;
  /** Only watch the elements matching this CSS selector. */
  selector?: string;
  /** Regular expressions; matching text is ignored (timestamps, counters). */
  ignorePatterns?: string[];
  minChangeChars?: number;
  notifyEmail?: boolean;
  jsRender?: boolean;
  useProxy?: boolean;
}

export interface Monitor {
  id: string;
  name: string;
  url: string;
  selector: string;
  interval_minutes: number;
  status: "active" | "paused";
  paused_reason?: string | null;
  checks: number;
  changes: number;
  last_checked_at?: string | null;
  last_changed_at?: string | null;
  next_check_at?: string | null;
  [k: string]: unknown;
}

export interface MonitorChange {
  id: string;
  created_at: string;
  summary: string;
  preview: string;
  diff: string;
  added: number;
  removed: number;
  [k: string]: unknown;
}
