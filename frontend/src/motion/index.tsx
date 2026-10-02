/* eslint-disable react-refresh/only-export-components -- shared motion module:
   the spring tokens must live next to the primitives so every consumer imports
   one vocabulary; losing fast-refresh granularity here is acceptable. */
import { useEffect, useState, type ReactNode } from 'react';
import {
  AnimatePresence,
  MotionConfig,
  motion,
  useMotionValue,
  useReducedMotion,
  useSpring,
  useTransform,
  type HTMLMotionProps,
} from 'motion/react';

/**
 * UC Nexus motion system.
 *
 * One vocabulary for the whole app: physical, quick, never bouncy-for-fun.
 * - `springs.fast`  — chips, toggles, small state flips
 * - `springs.base`  — cards, rows, panels, dialogs, page entrances
 * - `springs.slow`  — large surfaces (rail collapse, master-detail resize)
 *
 * Everything respects prefers-reduced-motion via <MotionProvider> (transforms
 * collapse to opacity) and the explicit `useReducedMotion` checks below.
 */

export const springs = {
  fast: { type: 'spring', visualDuration: 0.22, bounce: 0.08 },
  base: { type: 'spring', visualDuration: 0.34, bounce: 0.14 },
  slow: { type: 'spring', visualDuration: 0.48, bounce: 0.16 },
} as const;

/** Wrap the app once; honors the OS reduced-motion setting. */
export function MotionProvider({ children }: { children: ReactNode }) {
  return <MotionConfig reducedMotion="user">{children}</MotionConfig>;
}

/** Fade-and-rise entrance for a single block. `x` slides it in sideways instead (or as well). */
export function FadeIn({
  children,
  delay = 0,
  x = 0,
  y = 10,
  ...rest
}: { children: ReactNode; delay?: number; x?: number; y?: number } & HTMLMotionProps<'div'>) {
  return (
    <motion.div
      initial={{ opacity: 0, x, y }}
      animate={{ opacity: 1, x: 0, y: 0 }}
      transition={{ ...springs.base, delay }}
      {...rest}
    >
      {children}
    </motion.div>
  );
}

/**
 * Route-level entrance. Key it by the route (or any identity that should
 * re-trigger the entrance). No exit phase — content swaps immediately and the
 * incoming view rises in, so navigation never feels slowed down.
 */
export function PageTransition({
  transitionKey,
  children,
}: {
  transitionKey: string;
  children: ReactNode;
}) {
  return (
    <motion.div
      key={transitionKey}
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={springs.base}
      style={{ minWidth: 0 }}
    >
      {children}
    </motion.div>
  );
}

/**
 * Which way an index last moved: 1 forward, -1 back, 0 before it has moved (#1086). For keyed
 * step and tab panels, so the incoming panel arrives from the side being travelled towards.
 */
export function useStepDirection(index: number) {
  const [prev, setPrev] = useState(index);
  const [direction, setDirection] = useState(0);
  if (index !== prev) {
    setDirection(index > prev ? 1 : -1);
    setPrev(index);
  }
  return direction;
}

/**
 * Whether this component has shown a loading state at any point in its life (#1084). Content that
 * arrives in place of a skeleton should reveal; content served straight from cache on a revisit
 * should just be there, so pass this to <Reveal when>.
 */
export function useHadLoading(loading: boolean) {
  const [had, setHad] = useState(loading);
  if (loading && !had) setHad(true);
  return had || loading;
}

/**
 * Content taking a skeleton's place fades in rather than cutting over it (#1084). Opacity only: the
 * data lands where its skeleton stood, so moving it would read as the layout settling. With `when`
 * false it renders in place with no animation.
 */
export function Reveal({
  when,
  children,
  style,
}: {
  when: boolean;
  children: ReactNode;
  style?: React.CSSProperties;
}) {
  return (
    <motion.div
      initial={when ? { opacity: 0 } : false}
      animate={{ opacity: 1 }}
      transition={springs.base}
      style={{ minWidth: 0, ...style }}
    >
      {children}
    </motion.div>
  );
}

/** `springs.base` with the overshoot taken out, for height: a block that grows past its content and settles back makes everything below it wobble. */
const settle = { type: 'spring', visualDuration: springs.base.visualDuration, bounce: 0 } as const;

/**
 * Open and close a block's own height. It clips only while moving: at rest the overflow is visible
 * again, so a focus ring or a shadow at the block's edge is never cut off.
 */
const openClose = {
  initial: { height: 0, opacity: 0, overflow: 'hidden' },
  animate: { height: 'auto', opacity: 1, transitionEnd: { overflow: 'visible' } },
  exit: { height: 0, opacity: 0, overflow: 'hidden' },
  transition: settle,
} as const;

/**
 * A block that comes and goes while someone is working (an inline warning that follows what they
 * type, say) opens its own space and closes it again, so the content below glides instead of
 * jumping (#1085). Present on first render, it is simply there. Margins belong inside: the block
 * measures them, so they open and close with it.
 */
export function Appear({ show, children }: { show: boolean; children: ReactNode }) {
  return (
    <AnimatePresence initial={false}>
      {show && (
        <motion.div key="appear" {...openClose} style={{ minWidth: 0 }}>
          {children}
        </motion.div>
      )}
    </AnimatePresence>
  );
}

const staggerContainer = {
  hidden: {},
  show: (staggerChildren: number) => ({
    transition: { staggerChildren, delayChildren: 0.04 },
  }),
};

const staggerChild = {
  hidden: { opacity: 0, y: 10 },
  show: { opacity: 1, y: 0, transition: springs.base },
};

/**
 * Staggered entrance for a set of siblings (stat tiles, card grids, feed rows).
 * Wrap the group in <StaggerList> and each child in <StaggerItem>.
 * The per-child delay shrinks automatically for long lists so the tail never lags.
 */
export function StaggerList({
  children,
  count,
  style,
}: {
  children: ReactNode;
  /** Number of children, used to cap the total stagger at ~0.45s. */
  count?: number;
  style?: React.CSSProperties;
}) {
  const per = count && count > 0 ? Math.min(0.05, 0.45 / count) : 0.05;
  return (
    <motion.div
      variants={staggerContainer}
      custom={per}
      initial="hidden"
      animate="show"
      style={{ display: 'contents', ...style }}
    >
      {children}
    </motion.div>
  );
}

export function StaggerItem({
  children,
  style,
  ...rest
}: { children: ReactNode; style?: React.CSSProperties } & HTMLMotionProps<'div'>) {
  return (
    <motion.div variants={staggerChild} style={{ minWidth: 0, ...style }} {...rest}>
      {children}
    </motion.div>
  );
}

/**
 * A number that counts to its value on mount and re-animates on change.
 * Tabular numerals so the layout never jitters. Falls back to a plain value
 * under reduced motion.
 */
export function AnimatedNumber({
  value,
  format,
}: {
  value: number;
  format?: (n: number) => string;
}) {
  const reduced = useReducedMotion();
  const mv = useMotionValue(reduced ? value : 0);
  const spring = useSpring(mv, { stiffness: 170, damping: 26, mass: 0.9 });
  const text = useTransform(() => {
    const rounded = Math.round(spring.get());
    return format ? format(rounded) : String(rounded);
  });

  useEffect(() => {
    mv.set(value);
  }, [value, mv]);

  if (reduced) {
    return <span style={{ fontVariantNumeric: 'tabular-nums' }}>{format ? format(value) : value}</span>;
  }
  return <motion.span style={{ fontVariantNumeric: 'tabular-nums' }}>{text}</motion.span>;
}
