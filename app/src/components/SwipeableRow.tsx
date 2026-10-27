import { animate, motion, useMotionValue, useReducedMotion, useTransform } from "motion/react";
import { ArrowLeftRight, Tag } from "lucide-react";
import { useCallback, useEffect, useId, useRef, type ComponentType, type ReactNode } from "react";
import { ACTION_WIDTH, COMMIT_RATIO, resolveSwipe } from "@/lib/swipe";

const OPEN_EVENT = "swipe-row-open";

export interface SwipeableRowProps {
  children: ReactNode;
  /** Finger moved left (physical): reveals the action on the right edge. */
  onSwipeLeft?: () => void;
  /** Finger moved right (physical): reveals the action on the left edge. */
  onSwipeRight?: () => void;
  leftLabel?: string;
  rightLabel?: string;
  /** Icons and colours of the revealed actions; default to the transaction-row pair (tag / offset). */
  leftIcon?: ComponentType<{ className?: string }>;
  rightIcon?: ComponentType<{ className?: string }>;
  leftClass?: string;
  rightClass?: string;
}

/** Gmail-iOS-style swipe row: drag to reveal a tappable action, or swipe all the way / flick to run it. Only one row stays open at a time. */
export function SwipeableRow({
  children,
  onSwipeLeft,
  onSwipeRight,
  leftLabel = "שייך קטגוריה",
  rightLabel = "קזז",
  leftIcon: LeftIcon = Tag,
  rightIcon: RightIcon = ArrowLeftRight,
  leftClass = "bg-[var(--lg-primary)]",
  rightClass = "bg-good",
}: SwipeableRowProps) {
  const id = useId();
  const reduced = useReducedMotion();
  const x = useMotionValue(0);
  const ref = useRef<HTMLDivElement>(null);
  const dragged = useRef(false);
  const openSide = useRef<"left" | "right" | null>(null);

  const snap = useCallback(
    (to: number) => {
      if (reduced) x.set(to);
      else animate(x, to, { type: "spring", stiffness: 500, damping: 40 });
    },
    [reduced, x],
  );
  const close = useCallback(() => {
    openSide.current = null;
    snap(0);
  }, [snap]);

  useEffect(() => {
    const onOther = (e: Event) => {
      if ((e as CustomEvent<string>).detail !== id && openSide.current) close();
    };
    const onScroll = () => {
      if (openSide.current) close();
    };
    window.addEventListener(OPEN_EVENT, onOther);
    // Capture phase: scroll does not bubble, so this also catches nested scroll containers.
    document.addEventListener("scroll", onScroll, { capture: true, passive: true });
    return () => {
      window.removeEventListener(OPEN_EVENT, onOther);
      document.removeEventListener("scroll", onScroll, { capture: true });
    };
  }, [id, close]);

  // Left-swipe action sits on the right edge (x < 0); right-swipe action on the left edge (x > 0).
  const rightOpacity = useTransform(x, [0, -24, -ACTION_WIDTH], [0, 0.6, 1]);
  const leftOpacity = useTransform(x, [0, 24, ACTION_WIDTH], [0, 0.6, 1]);
  const commitAt = () => (ref.current?.offsetWidth ?? 390) * COMMIT_RATIO;
  const rightScale = useTransform(x, (v) => (-v >= commitAt() ? 1.3 : 1));
  const leftScale = useTransform(x, (v) => (v >= commitAt() ? 1.3 : 1));

  if (!onSwipeLeft && !onSwipeRight) return <>{children}</>;

  const run = (cb?: () => void) => {
    cb?.();
    close();
  };
  const commit = (dir: -1 | 1, cb?: () => void) => {
    navigator.vibrate?.(10);
    openSide.current = null;
    const width = ref.current?.offsetWidth ?? 390;
    if (reduced) {
      cb?.();
      x.set(0);
      return;
    }
    animate(x, dir * width * 0.7, { duration: 0.12, ease: "easeOut" }).then(() => {
      cb?.();
      snap(0);
    });
  };

  return (
    <div ref={ref} className="relative overflow-hidden">
      {onSwipeLeft ? (
        <motion.button
          type="button"
          // A touch shortcut only: the row's edit sheet offers both actions to keyboard and screen readers.
          tabIndex={-1}
          aria-hidden
          style={{ opacity: rightOpacity, width: ACTION_WIDTH }}
          onClick={() => run(onSwipeLeft)}
          className={`absolute inset-y-0 right-0 flex flex-col items-center justify-center gap-1 ${leftClass} text-[11px] font-semibold text-[var(--lg-on-accent)]`}
        >
          <motion.span style={{ scale: rightScale }} className="flex">
            <LeftIcon className="size-5" />
          </motion.span>
          {leftLabel}
        </motion.button>
      ) : null}
      {onSwipeRight ? (
        <motion.button
          type="button"
          tabIndex={-1}
          aria-hidden
          style={{ opacity: leftOpacity, width: ACTION_WIDTH }}
          onClick={() => run(onSwipeRight)}
          className={`absolute inset-y-0 left-0 flex flex-col items-center justify-center gap-1 ${rightClass} text-[11px] font-semibold text-[var(--lg-on-accent)]`}
        >
          <motion.span style={{ scale: leftScale }} className="flex">
            <RightIcon className="size-5" />
          </motion.span>
          {rightLabel}
        </motion.button>
      ) : null}
      <motion.div
        drag="x"
        dragDirectionLock
        dragConstraints={{ left: 0, right: 0 }}
        dragElastic={{ left: onSwipeLeft ? 0.9 : 0, right: onSwipeRight ? 0.9 : 0 }}
        dragMomentum={false}
        style={{ x, touchAction: "pan-y" }}
        className="relative bg-panel"
        onDragStart={() => {
          dragged.current = true;
          window.dispatchEvent(new CustomEvent(OPEN_EVENT, { detail: id }));
        }}
        onDragEnd={(_, info) => {
          setTimeout(() => (dragged.current = false), 0);
          const out = resolveSwipe({
            offset: info.offset.x,
            velocity: info.velocity.x,
            width: ref.current?.offsetWidth ?? 390,
            canLeft: !!onSwipeLeft,
            canRight: !!onSwipeRight,
          });
          if (out === "commit-left") commit(-1, onSwipeLeft);
          else if (out === "commit-right") commit(1, onSwipeRight);
          else if (out === "open-left") {
            openSide.current = "left";
            snap(-ACTION_WIDTH);
          } else if (out === "open-right") {
            openSide.current = "right";
            snap(ACTION_WIDTH);
          } else close();
        }}
        onClickCapture={(e) => {
          if (dragged.current) {
            e.stopPropagation();
            e.preventDefault();
          } else if (openSide.current) {
            // A tap on an opened row just closes it.
            e.stopPropagation();
            e.preventDefault();
            close();
          }
        }}
      >
        {children}
      </motion.div>
    </div>
  );
}
