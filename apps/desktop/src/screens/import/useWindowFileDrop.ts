import { useEffect, useEffectEvent, useState } from "react";

/**
 * Accept files dragged onto any part of the window, and report whether files are being dragged
 * over it. (Tauri's own drag-and-drop handling is turned off, so the webview gets the standard
 * HTML5 events.)
 *
 * Drags that carry no files, such as selected text, are left alone. While `enabled` is false,
 * drops are still swallowed, so a stray file never makes the webview navigate away from the app,
 * but `onDrop` isn't called.
 */
export function useWindowFileDrop(onDrop: (files: File[]) => void, enabled: boolean): boolean {
  const [dragging, setDragging] = useState(false);
  const handleDrop = useEffectEvent(onDrop);
  const isEnabled = useEffectEvent(() => enabled);

  useEffect(() => {
    // dragenter and dragleave fire for every element crossed, so count to know when the drag
    // has really left the window.
    let depth = 0;

    function onDragEnter(event: DragEvent) {
      if (!carriesFiles(event)) return;
      event.preventDefault();
      depth += 1;
      setDragging(true);
    }
    function onDragOver(event: DragEvent) {
      if (!carriesFiles(event)) return;
      // Cancelling dragover is what allows a drop.
      event.preventDefault();
      if (event.dataTransfer) event.dataTransfer.dropEffect = isEnabled() ? "copy" : "none";
    }
    function onDragLeave(event: DragEvent) {
      if (!carriesFiles(event)) return;
      depth = Math.max(0, depth - 1);
      if (depth === 0) setDragging(false);
    }
    function onDropEvent(event: DragEvent) {
      if (!carriesFiles(event)) return;
      event.preventDefault();
      depth = 0;
      setDragging(false);
      if (isEnabled()) handleDrop(Array.from(event.dataTransfer?.files ?? []));
    }

    window.addEventListener("dragenter", onDragEnter);
    window.addEventListener("dragover", onDragOver);
    window.addEventListener("dragleave", onDragLeave);
    window.addEventListener("drop", onDropEvent);
    return () => {
      window.removeEventListener("dragenter", onDragEnter);
      window.removeEventListener("dragover", onDragOver);
      window.removeEventListener("dragleave", onDragLeave);
      window.removeEventListener("drop", onDropEvent);
    };
  }, []);

  return dragging && enabled;
}

function carriesFiles(event: DragEvent): boolean {
  return event.dataTransfer?.types.includes("Files") ?? false;
}
