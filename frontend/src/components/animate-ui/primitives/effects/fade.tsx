'use client';

import * as React from 'react';
import { motion, type HTMLMotionProps } from 'motion/react';

import {
  useIsInView,
  type UseIsInViewOptions,
} from '@/hooks/use-is-in-view';
// MeshMind uses a div wrapper only. The optional upstream asChild adapter is
// omitted to avoid creating motion component types while React renders.
type FadeProps =
  {
    children?: React.ReactNode;
    delay?: number;
    initialOpacity?: number;
    opacity?: number;
    ref?: React.Ref<HTMLDivElement>;
  } & UseIsInViewOptions &
    HTMLMotionProps<'div'>;

function Fade({
  ref,
  transition = { type: 'spring', stiffness: 200, damping: 20 },
  delay = 0,
  inView = false,
  inViewMargin = '0px',
  inViewOnce = true,
  initialOpacity = 0,
  opacity = 1,
  ...props
}: FadeProps) {
  const { ref: localRef, isInView } = useIsInView(
    ref as React.Ref<HTMLElement>,
    {
      inView,
      inViewOnce,
      inViewMargin,
    },
  );

  return (
    <motion.div
      ref={localRef as React.Ref<HTMLDivElement>}
      initial="hidden"
      animate={isInView ? 'visible' : 'hidden'}
      exit="hidden"
      variants={{
        hidden: { opacity: initialOpacity },
        visible: { opacity },
      }}
      transition={{
        ...transition,
        delay: (transition?.delay ?? 0) + delay / 1000,
      }}
      {...props}
    />
  );
}

type FadeListProps = Omit<FadeProps, 'children'> & {
  children: React.ReactElement | React.ReactElement[];
  holdDelay?: number;
};

function Fades({
  children,
  delay = 0,
  holdDelay = 0,
  ...props
}: FadeListProps) {
  const array = React.Children.toArray(children) as React.ReactElement[];

  return (
    <>
      {array.map((child, index) => (
        <Fade
          key={child.key ?? index}
          delay={delay + index * holdDelay}
          {...props}
        >
          {child}
        </Fade>
      ))}
    </>
  );
}

export { Fade, Fades, type FadeProps, type FadeListProps };
