"use client";
// Adapted from Aceternity UI "Stars Background" (https://ui.aceternity.com/components/shooting-stars-and-stars-background).
// Changes: device-pixel-ratio aware canvas, configurable star size, optional seed for a stable sky, resize observer cleanup.
import { cn } from "@/lib/utils";
import React, { useCallback, useEffect, useRef, useState } from "react";

interface StarProps {
  x: number;
  y: number;
  radius: number;
  opacity: number;
  twinkleSpeed: number | null;
}

interface StarBackgroundProps {
  starDensity?: number;
  allStarsTwinkle?: boolean;
  twinkleProbability?: number;
  minTwinkleSpeed?: number;
  maxTwinkleSpeed?: number;
  minRadius?: number;
  maxRadius?: number;
  /** Same seed and viewport always produce the same sky. */
  seed?: number;
  className?: string;
}

/** Small deterministic PRNG (mulberry32). */
function seededRandom(seed: number) {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export const StarsBackground: React.FC<StarBackgroundProps> = ({
  starDensity = 0.00015,
  allStarsTwinkle = true,
  twinkleProbability = 0.7,
  minTwinkleSpeed = 0.5,
  maxTwinkleSpeed = 1,
  minRadius = 0.5,
  maxRadius = 0.55,
  seed,
  className,
}) => {
  const [stars, setStars] = useState<StarProps[]>([]);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  const generateStars = useCallback(
    (width: number, height: number): StarProps[] => {
      const numStars = Math.floor(width * height * starDensity);
      const random = seed === undefined ? Math.random : seededRandom(seed);
      return Array.from({ length: numStars }, () => {
        const shouldTwinkle = allStarsTwinkle || random() < twinkleProbability;
        return {
          x: random() * width,
          y: random() * height,
          radius: minRadius + random() * (maxRadius - minRadius),
          opacity: random() * 0.5 + 0.5,
          twinkleSpeed: shouldTwinkle ? minTwinkleSpeed + random() * (maxTwinkleSpeed - minTwinkleSpeed) : null,
        };
      });
    },
    [starDensity, allStarsTwinkle, twinkleProbability, minTwinkleSpeed, maxTwinkleSpeed, minRadius, maxRadius, seed],
  );

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const updateStars = () => {
      const { width, height } = canvas.getBoundingClientRect();
      const ratio = window.devicePixelRatio || 1;
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
      canvas.getContext("2d")?.setTransform(ratio, 0, 0, ratio, 0, 0);
      setStars(generateStars(width, height));
    };
    updateStars();
    const resizeObserver = new ResizeObserver(updateStars);
    resizeObserver.observe(canvas);
    return () => resizeObserver.disconnect();
  }, [generateStars]);

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    let animationFrameId = 0;
    const render = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      stars.forEach((star) => {
        ctx.beginPath();
        ctx.arc(star.x, star.y, star.radius, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(255, 255, 255, ${star.opacity})`;
        ctx.fill();
        if (star.twinkleSpeed !== null) star.opacity = 0.5 + Math.abs(Math.sin((Date.now() * 0.001) / star.twinkleSpeed) * 0.5);
      });
      animationFrameId = requestAnimationFrame(render);
    };
    render();
    return () => cancelAnimationFrame(animationFrameId);
  }, [stars]);

  return <canvas ref={canvasRef} className={cn("absolute inset-0 h-full w-full", className)} />;
};
