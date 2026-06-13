import { type SyntheticEvent, useEffect, useMemo, useRef, useState } from "react";

type Props = {
  emailId: number;
  html: string;
};

const MIN_HEIGHT = 160;
const MAX_HEIGHT = 900;

export function EmailHtmlFrame({ emailId, html }: Props) {
  const hostRef = useRef<HTMLDivElement>(null);
  const [shouldRender, setShouldRender] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [height, setHeight] = useState(MIN_HEIGHT);
  const cacheKey = useMemo(() => `emailchrono:v2:render:${emailId}:${hashText(html)}`, [emailId, html]);
  const srcDoc = useMemo(() => {
    const cached = readCache(cacheKey);
    if (cached) return cached;
    const wrapped = wrapEmailHtml(html);
    writeCache(cacheKey, wrapped);
    return wrapped;
  }, [cacheKey, html]);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setShouldRender(true);
          observer.disconnect();
        }
      },
      { rootMargin: "320px" }
    );
    observer.observe(host);
    return () => observer.disconnect();
  }, []);

  function onLoad(event: SyntheticEvent<HTMLIFrameElement>) {
    const doc = event.currentTarget.contentDocument;
    const nextHeight = Math.min(
      MAX_HEIGHT,
      Math.max(MIN_HEIGHT, (doc?.documentElement?.scrollHeight || doc?.body?.scrollHeight || MIN_HEIGHT) + 16)
    );
    setHeight(nextHeight);
    setLoaded(true);
  }

  return (
    <div className="email-html-frame" ref={hostRef} style={{ minHeight: height }}>
      {!loaded && <div className="email-html-skeleton">Loading rendered email...</div>}
      {shouldRender && (
        <iframe
          srcDoc={srcDoc}
          sandbox="allow-same-origin"
          title={`Rendered email ${emailId}`}
          style={{ height, opacity: loaded ? 1 : 0 }}
          onLoad={onLoad}
        />
      )}
    </div>
  );
}

function wrapEmailHtml(html: string) {
  return `<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src cid: data:; style-src 'unsafe-inline'; script-src 'none'; object-src 'none'; base-uri 'none'; connect-src 'none'; form-action 'none';">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    html, body { margin: 0; padding: 0; background: #fff; color: #111827; }
    body { font-family: Arial, Helvetica, sans-serif; font-size: 14px; line-height: 1.45; overflow-wrap: anywhere; }
    img { max-width: 100%; height: auto; }
    table { max-width: 100%; border-collapse: collapse; }
    td, th { overflow-wrap: anywhere; }
    a { color: #2563eb; }
  </style>
</head>
<body>${html}</body>
</html>`;
}

function hashText(value: string) {
  let hash = 0;
  for (let index = 0; index < value.length; index += 1) {
    hash = (hash * 31 + value.charCodeAt(index)) | 0;
  }
  return Math.abs(hash).toString(36);
}

function readCache(key: string) {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeCache(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Storage may be full or unavailable; rendering can continue without caching.
  }
}
