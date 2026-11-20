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
