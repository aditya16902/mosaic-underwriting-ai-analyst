import { ReactNode } from "react";
import { MessageSquareText, X } from "lucide-react";
import { useResizablePanel } from "./useResizablePanel";
import clsx from "clsx";

interface ResizableChatPanelProps {
  children: ReactNode;
  panelState: ReturnType<typeof useResizablePanel>;
}

/**
 * The persistent right-side chat panel shell — VS Code-style drag handle
 * on the left edge, collapsible, width persisted for the session.
 * Content (the actual chat UI) is passed as children so this stays pure layout.
 */
export function ResizableChatPanel({ children, panelState }: ResizableChatPanelProps) {
  const { width, isOpen, isDragging, close, onDragStart } = panelState;

  if (!isOpen) return null;

  return (
    <div
      className="relative flex-shrink-0 h-full bg-panel border-l border-line flex flex-col"
      style={{ width }}
    >
      {/* Drag handle */}
      <div
        onPointerDown={onDragStart}
        className={clsx(
          "absolute left-0 top-0 h-full w-1.5 -translate-x-1/2 cursor-col-resize z-10 group",
          isDragging && "bg-house/30",
        )}
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize chat panel"
      >
        <div
          className={clsx(
            "absolute left-1/2 top-0 h-full w-px -translate-x-1/2 bg-line transition-colors",
            "group-hover:bg-house group-hover:w-0.5",
            isDragging && "bg-house w-0.5",
          )}
        />
      </div>

      <header className="flex items-center justify-between px-4 py-3 border-b border-line">
        <div className="flex items-center gap-2">
          <MessageSquareText size={16} className="text-house" strokeWidth={2} />
          <span className="font-medium text-sm text-ink">Ask MosAIc</span>
        </div>
        <button
          onClick={close}
          className="text-warmgray hover:text-ink transition-colors p-1 rounded"
          aria-label="Close chat panel"
        >
          <X size={16} />
        </button>
      </header>

      <div className="flex-1 overflow-hidden flex flex-col">{children}</div>
    </div>
  );
}

export function ChatPanelToggle({ onOpen }: { onOpen: () => void }) {
  return (
    <button
      onClick={onOpen}
      className="fixed right-5 bottom-5 z-20 flex items-center gap-2 bg-ink text-page px-4 py-3 rounded-full shadow-lg hover:bg-house transition-colors"
      aria-label="Open chat panel"
    >
      <MessageSquareText size={18} strokeWidth={2} />
      <span className="text-sm font-medium pr-0.5">Ask MosAIc</span>
    </button>
  );
}
