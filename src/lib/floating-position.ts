export type FloatingPosition = {
  left: number;
  top: number;
};

/**
 * Places a floating panel toward the inside of the viewport.
 *
 * - Triggers on the right half open to the left.
 * - Triggers on the left half open to the right.
 * - Triggers in the lower half prefer opening above.
 * - The final position is always clamped to the viewport margin.
 */
export function getInwardFloatingPosition(
  trigger: DOMRect,
  floating: Pick<DOMRect, "width" | "height">,
  options: { margin?: number; gap?: number } = {},
): FloatingPosition {
  const margin = options.margin ?? 12;
  const gap = options.gap ?? 8;
  const viewportWidth = window.innerWidth;
  const viewportHeight = window.innerHeight;

  const openLeft = trigger.left + trigger.width / 2 > viewportWidth / 2;
  const openAbove = trigger.top + trigger.height / 2 > viewportHeight / 2;

  let left = openLeft
    ? trigger.right - floating.width
    : trigger.left;

  let top = openAbove
    ? trigger.top - floating.height - gap
    : trigger.bottom + gap;

  // If the preferred vertical side has no room, try the opposite side first.
  if (top < margin && trigger.bottom + gap + floating.height <= viewportHeight - margin) {
    top = trigger.bottom + gap;
  } else if (
    top + floating.height > viewportHeight - margin &&
    trigger.top - gap - floating.height >= margin
  ) {
    top = trigger.top - floating.height - gap;
  }

  left = Math.min(
    Math.max(margin, left),
    Math.max(margin, viewportWidth - floating.width - margin),
  );
  top = Math.min(
    Math.max(margin, top),
    Math.max(margin, viewportHeight - floating.height - margin),
  );

  return { left, top };
}
