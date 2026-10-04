"use client";
import { useReducedMotion } from "motion/react";
import { Fade } from "@/components/animate-ui/primitives/effects/fade";
export function Reveal({children}:{children:React.ReactNode}) {
  const reduced = useReducedMotion();
  return <Fade className="motion-entry" initialOpacity={reduced ? 1 : 0.92} transition={{type:"tween",duration:reduced ? 0 : 0.25}}>{children}</Fade>;
}
