export type ActorMotionState = "idle" | "walk" | "interact" | "talk";

export function resolvePlayerMotionState(
  playerX: number,
  targetX: number,
  playerY: number,
  targetY: number,
  interactionMode: "none" | "inspect" | "talk",
): ActorMotionState {
  if (Math.hypot(playerX - targetX, playerY - targetY) > 0.04) return "walk";
  if (interactionMode === "inspect") return "interact";
  if (interactionMode === "talk") return "talk";
  return "idle";
}
