import { useCallback, useEffect, useRef, useState } from "react";

const MIN_PANEL_WIDTH = 320;
const MAX_PANEL_WIDTH_RATIO = 0.65; // never let the chat panel eat more than 65% of the viewport
const DEFAULT_PANEL_WIDTH = 420;
const COLLAPSE_THRESHOLD = 220; // dragging narrower than this snaps the panel closed

/**
 * VS Code-style resizable side panel.
 * Drag the left edge handle to resize; drag past COLLAPSE_THRESHOLD to snap closed.
 * Width persists across the session via sessionStorage so a reload mid-task
 * doesn't reset the layout the CUO just arranged.
 */
export function useResizablePanel(storageKey = "mosaic_chat_panel_width") {
  const [width, setWidth] = useState<number>(() => {
    const stored = sessionStorage.getItem(storageKey);
    return stored ? Number(stored) : DEFAULT_PANEL_WIDTH;
  });
  const [isOpen, setIsOpen] = useState<boolean>(() => {
    const stored = sessionStorage.getItem(`${storageKey}_open`);
    return stored === null ? true : stored === "true";
  });
  const [isDragging, setIsDragging] = useState(false);
  const dragStartX = useRef(0);
  const dragStartWidth = useRef(0);

  useEffect(() => {
    sessionStorage.setItem(storageKey, String(width));
  }, [width, storageKey]);

  useEffect(() => {
    sessionStorage.setItem(`${storageKey}_open`, String(isOpen));
  }, [isOpen, storageKey]);

  const onDragStart = useCallback(
    (e: React.PointerEvent) => {
      e.preventDefault();
      dragStartX.current = e.clientX;
      dragStartWidth.current = width;
      setIsDragging(true);
    },
    [width],
  );

  useEffect(() => {
    if (!isDragging) return;

    const maxWidth = window.innerWidth * MAX_PANEL_WIDTH_RATIO;

    function onMove(e: PointerEvent) {
      // Panel is on the right edge — dragging left (negative delta) grows it.
      const delta = dragStartX.current - e.clientX;
      const next = dragStartWidth.current + delta;
      setWidth(Math.min(Math.max(next, 0), maxWidth));
    }

    function onUp() {
      setIsDragging(false);
      setWidth((current) => {
        if (current < COLLAPSE_THRESHOLD) {
          setIsOpen(false);
          return DEFAULT_PANEL_WIDTH;
        }
        return Math.max(current, MIN_PANEL_WIDTH);
      });
    }

    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
  }, [isDragging]);

  return {
    width,
    isOpen,
    isDragging,
    open: () => setIsOpen(true),
    close: () => setIsOpen(false),
    toggle: () => setIsOpen((v) => !v),
    onDragStart,
  };
}
