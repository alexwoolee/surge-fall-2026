"use client";
import { ImageDithering } from "@paper-design/shaders-react";
import { ShootingStars } from "@/components/ui/shooting-stars";
import { StarsBackground } from "@/components/ui/stars-background";
import glowSource from "@/assets/glow-source.png";

/** Dither dot colour. White for testing; the earlier indigo was front #343f8a / highlight #6874c8. */
const DITHER_COLOR = "#ffffff";

/** One Paper Shaders dither of a soft radial gradient; placement and shape come from CSS. */
function DitherGlow({ placement }: { placement: "left" | "right" | "bottom" }) {
  return <ImageDithering className={`space-glow space-glow--${placement}`} image={glowSource.src} colorBack="#00000000" colorFront={DITHER_COLOR} colorHighlight={DITHER_COLOR} type="4x4" size={2} colorSteps={3} fit="cover" maxPixelCount={900 * 900} />;
}

/**
 * One fixed, viewport-sized backdrop mounted by the root layout, so it is identical on every
 * route and never remounts during navigation. Dithered glows sit bottom-left, right, and along
 * the bottom edge behind the chat composer; each is masked to a circle so the shader's faint
 * near-black dots never show a rectangular edge. The backdrop is decorative and slow, so it keeps
 * animating even when the OS requests reduced motion (Windows reports that whenever
 * "Animation effects" is off).
 */
export function SpaceBackground() {
  return <div className="space-background" aria-hidden="true">
    <DitherGlow placement="left" />
    <DitherGlow placement="right" />
    <DitherGlow placement="bottom" />
    <StarsBackground seed={20261004} starDensity={0.00018} minRadius={0.6} maxRadius={1.15} />
    <ShootingStars starColor="#e6e6ff" trailColor="#6d7cff" minDelay={2400} maxDelay={6800} />
  </div>;
}
