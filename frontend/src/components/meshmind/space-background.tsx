"use client";
import { GrainGradient } from "@paper-design/shaders-react";
import { ShootingStars } from "@/components/ui/shooting-stars";
import { StarsBackground } from "@/components/ui/stars-background";

/**
 * Fixed full-viewport backdrop shared by every workspace view. The background is purely
 * decorative and slow, so it keeps animating even when the OS requests reduced motion
 * (Windows reports that whenever "Animation effects" is off).
 */
export function SpaceBackground() {
  return <div className="space-background" aria-hidden="true">
    <GrainGradient className="space-glow" shape="wave" colorBack="#0c0b0a" colors={["#2b3166", "#3a2954", "#1c3646"]} softness={1} intensity={0.25} noise={0.35} speed={0.3} scale={1.4} maxPixelCount={640 * 640} />
    <StarsBackground starDensity={0.00018} minRadius={0.6} maxRadius={1.15} />
    <ShootingStars starColor="#e6e6ff" trailColor="#6d7cff" minDelay={2400} maxDelay={6800} />
  </div>;
}
