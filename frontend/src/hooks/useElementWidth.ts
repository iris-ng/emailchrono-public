import { useEffect, useRef, useState } from "react";

/**
 * Tracks the rendered width of an element via ResizeObserver. Used to make the
 * toolbar collapse based on the panel's own width (which changes when the left
 * sidebar is resized/collapsed) rather than the viewport width.
 */
export function useElementWidth<T extends HTMLElement>() {
  const ref = useRef<T | null>(null);
  const [width, setWidth] = useState(0);

  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const observer = new ResizeObserver((entries) => {
      const measured = entries[0]?.contentRect.width;
      if (typeof measured === "number") setWidth(measured);
    });
    observer.observe(element);
    setWidth(element.getBoundingClientRect().width);
    return () => observer.disconnect();
  }, []);

  return [ref, width] as const;
}
