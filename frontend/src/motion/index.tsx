import { useEffect, type ReactNode } from 'react';
import {
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

/** Fade-and-rise entrance for a single block. */
export function FadeIn({
  children,
  delay = 0,
  y = 10,
  ...rest
}: { children: ReactNode; delay?: number; y?: number } & HTMLMotionProps<'div'>) {
  return (
    <motion.div
      initial={{ opacity: 0, y }}
      animate={{ opacity: 1, y: 0 }}
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
