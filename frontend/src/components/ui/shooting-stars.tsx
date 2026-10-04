"use client";
// Adapted from Aceternity UI "Shooting Stars" (https://ui.aceternity.com/components/shooting-stars-and-stars-background).
// Changes: spawn timer is cleared on unmount, unique gradient id.
import { cn } from "@/lib/utils";
import React, { useEffect, useId, useState } from "react";

interface ShootingStar {
  id: number;
  x: number;
  y: number;
  angle: number;
  scale: number;
  speed: number;
  distance: number;
}

interface ShootingStarsProps {
  minSpeed?: number;
  maxSpeed?: number;
  minDelay?: number;
  maxDelay?: number;
  starColor?: string;
  trailColor?: string;
  starWidth?: number;
  starHeight?: number;
  className?: string;
}

const getRandomStartPoint = () => {
  const side = Math.floor(Math.random() * 4);
  const offset = Math.random() * window.innerWidth;
  switch (side) {
    case 0: return { x: offset, y: 0, angle: 45 };
    case 1: return { x: window.innerWidth, y: offset, angle: 135 };
    case 2: return { x: offset, y: window.innerHeight, angle: 225 };
    case 3: return { x: 0, y: offset, angle: 315 };
    default: return { x: 0, y: 0, angle: 45 };
  }
};

export const ShootingStars: React.FC<ShootingStarsProps> = ({
  minSpeed = 10,
  maxSpeed = 30,
  minDelay = 1200,
  maxDelay = 4200,
  starColor = "#9E00FF",
  trailColor = "#2EB9DF",
  starWidth = 10,
  starHeight = 1,
  className,
}) => {
  const [star, setStar] = useState<ShootingStar | null>(null);
  const gradientId = `shooting-star-${useId().replace(/:/g, "")}`;

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    const createStar = () => {
      const { x, y, angle } = getRandomStartPoint();
      setStar({ id: Date.now(), x, y, angle, scale: 1, speed: Math.random() * (maxSpeed - minSpeed) + minSpeed, distance: 0 });
      timer = setTimeout(createStar, Math.random() * (maxDelay - minDelay) + minDelay);
    };
    createStar();
    return () => clearTimeout(timer);
  }, [minSpeed, maxSpeed, minDelay, maxDelay]);

  useEffect(() => {
    if (!star) return;
    const animationFrame = requestAnimationFrame(() => {
      setStar((prevStar) => {
        if (!prevStar) return null;
        const newX = prevStar.x + prevStar.speed * Math.cos((prevStar.angle * Math.PI) / 180);
        const newY = prevStar.y + prevStar.speed * Math.sin((prevStar.angle * Math.PI) / 180);
        const newDistance = prevStar.distance + prevStar.speed;
        if (newX < -20 || newX > window.innerWidth + 20 || newY < -20 || newY > window.innerHeight + 20) return null;
        return { ...prevStar, x: newX, y: newY, distance: newDistance, scale: 1 + newDistance / 100 };
      });
    });
    return () => cancelAnimationFrame(animationFrame);
  }, [star]);

  return (
    <svg className={cn("absolute inset-0 h-full w-full", className)}>
      {star && (
        <rect
          key={star.id}
          x={star.x}
          y={star.y}
          width={starWidth * star.scale}
          height={starHeight}
          fill={`url(#${gradientId})`}
          transform={`rotate(${star.angle}, ${star.x + (starWidth * star.scale) / 2}, ${star.y + starHeight / 2})`}
        />
      )}
      <defs>
        <linearGradient id={gradientId} x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" style={{ stopColor: trailColor, stopOpacity: 0 }} />
          <stop offset="100%" style={{ stopColor: starColor, stopOpacity: 1 }} />
        </linearGradient>
      </defs>
    </svg>
  );
};
