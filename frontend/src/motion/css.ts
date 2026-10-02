/**
 * The spring tokens in `./index.tsx`, sampled into CSS `linear()` easings for the transitions Motion
 * does not drive: MUI's Collapse, Accordion and Dialog run on react-transition-group with a fixed
 * timeout, so they take a duration and a timing function, not a spring.
 *
 * Both curves are critically damped (no overshoot): a panel that grows past its content and settles
 * back reads as wobble on a ledger, not polish. `duration` includes the settle tail, so it is longer
 * than the felt duration (0.34s base, 0.22s fast); time sibling animations off the felt figure.
 * Generated with Motion's CSS spring generator; regenerate rather than hand-edit the points.
 */
export const cssSprings = {
  /** Felt 0.22s. Exits and small flips. */
  fast: {
    duration: 450,
    easing:
      'linear(0, 0.1787, 0.4522, 0.668, 0.8096, 0.8947, 0.9432, 0.97, 0.9843, 0.9919, 0.9959, 0.9979, 0.999, 0.9995, 1)',
  },
  /** Felt 0.34s. Panels opening, dialogs arriving. */
  base: {
    duration: 650,
    easing:
      'linear(0, 0.0832, 0.2471, 0.4185, 0.5681, 0.6879, 0.7789, 0.8458, 0.8937, 0.9275, 0.9509, 0.967, 0.978, 0.9853, 0.9903, 0.9936, 0.9958, 0.9972, 0.9982, 0.9988, 0.9992, 1)',
  },
  /** Felt 0.48s. Large surfaces: the nav rail collapsing. */
  slow: {
    duration: 850,
    easing:
      'linear(0, 0.0471, 0.1512, 0.2754, 0.399, 0.512, 0.6101, 0.6924, 0.7598, 0.814, 0.857, 0.8907, 0.9169, 0.9371, 0.9526, 0.9644, 0.9733, 0.9801, 0.9852, 0.989, 0.9918, 0.9939, 0.9955, 0.9967, 0.9976, 0.9982, 0.9987, 1)',
  },
} as const;

/** `<duration> <easing>` for a CSS `transition` shorthand. */
export const cssSpring = (token: keyof typeof cssSprings) =>
  `${cssSprings[token].duration}ms ${cssSprings[token].easing}`;

/** Enter on `base`, leave on `fast`: arriving content takes its time, departing content gets out of the way. */
export const cssSpringTransition = {
  timeout: { enter: cssSprings.base.duration, exit: cssSprings.fast.duration },
  easing: { enter: cssSprings.base.easing, exit: cssSprings.fast.easing },
};
