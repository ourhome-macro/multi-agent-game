import { useFrame } from "@react-three/fiber";
import { useRef } from "react";
import * as THREE from "three";

import { playerArt } from "../assets/artAssets";
import { resolvePlayerMotionState } from "./actorState";
import { SpritePlane } from "./SpritePlane";
import { useUiStore } from "../state/uiStore";

const walkBounds = {
  minX: -4.15,
  maxX: 4.15,
  minY: -1.3,
  maxY: -0.72,
};
const keyboardSpeed = 2.25;
const clickWalkSpeed = 1.18;
const arrivalSnapDistance = 0.018;

export function PlayerActor() {
  const groupRef = useRef<THREE.Group>(null);
  const facingRef = useRef(1);
  const playerX = useUiStore((store) => store.playerX);
  const playerY = useUiStore((store) => store.playerY);
  const targetX = useUiStore((store) => store.playerTargetX);
  const targetY = useUiStore((store) => store.playerTargetY);
  const playerMotion = useUiStore((store) => store.playerMotion);
  const keyboardVector = useUiStore((store) => store.keyboardVector);
  const setPlayerPosition = useUiStore((store) => store.setPlayerPosition);
  const setPlayerTarget = useUiStore((store) => store.setPlayerTarget);
  const setPlayerMotion = useUiStore((store) => store.setPlayerMotion);

  useFrame((_, delta) => {
    const keyboardMagnitude = Math.hypot(keyboardVector.x, keyboardVector.y);
    const hasKeyboardMovement = keyboardMagnitude > 0;
    let nextX = playerX;
    let nextY = playerY;

    if (hasKeyboardMovement) {
      const normalizedX = keyboardVector.x / keyboardMagnitude;
      const normalizedY = keyboardVector.y / keyboardMagnitude;
      nextX = THREE.MathUtils.clamp(
        playerX + normalizedX * keyboardSpeed * delta,
        walkBounds.minX,
        walkBounds.maxX,
      );
      nextY = THREE.MathUtils.clamp(
        playerY + normalizedY * keyboardSpeed * delta,
        walkBounds.minY,
        walkBounds.maxY,
      );
      setPlayerPosition(nextX, nextY);
      setPlayerTarget(nextX, nextY);
      if (playerMotion !== "walk") setPlayerMotion("walk");
    } else {
      const deltaX = targetX - playerX;
      const deltaY = targetY - playerY;
      const distance = Math.hypot(deltaX, deltaY);
      const step = Math.min(clickWalkSpeed * delta, distance);
      const ratio = distance > 0 ? step / distance : 0;
      nextX = playerX + deltaX * ratio;
      nextY = playerY + deltaY * ratio;
      const snappedX = Math.abs(nextX - targetX) < arrivalSnapDistance ? targetX : nextX;
      const snappedY = Math.abs(nextY - targetY) < arrivalSnapDistance ? targetY : nextY;
      setPlayerPosition(snappedX, snappedY);
      nextX = snappedX;
      nextY = snappedY;
    }

    const interactionMode =
      playerMotion === "talk" ? "talk" : playerMotion === "interact" ? "inspect" : "none";
    const nextMotion = hasKeyboardMovement
      ? "walk"
      : resolvePlayerMotionState(nextX, targetX, nextY, targetY, interactionMode);
    if (
      nextMotion !== playerMotion &&
      (nextMotion === "walk" || Math.hypot(nextX - targetX, nextY - targetY) < 0.04)
    ) {
      setPlayerMotion(nextMotion);
    }

    if (keyboardVector.x < -0.01 || (!hasKeyboardMovement && targetX < nextX - 0.01)) {
      facingRef.current = 1;
    } else if (keyboardVector.x > 0.01 || (!hasKeyboardMovement && targetX > nextX + 0.01)) {
      facingRef.current = -1;
    }

    if (groupRef.current) {
      groupRef.current.position.x = nextX;
      const walking = hasKeyboardMovement || Math.hypot(nextX - targetX, nextY - targetY) > 0.03;
      groupRef.current.position.y =
        nextY + (walking ? Math.abs(Math.sin(performance.now() / 115)) * 0.035 : 0);
      groupRef.current.rotation.z = Math.sin(performance.now() / 160) * (walking ? 0.026 : 0.006);
      groupRef.current.scale.x = facingRef.current;
    }
  });

  return (
    <group ref={groupRef} position={[playerX, playerY, 0.45]}>
      <mesh position={[0, -0.43, -0.03]} scale={[1.35, 0.26, 1]}>
        <circleGeometry args={[0.28, 24]} />
        <meshBasicMaterial color="#050505" transparent opacity={0.46} />
      </mesh>
      <SpritePlane
        src={playerArt.src}
        width={(playerArt.width / playerArt.height) * 1.5}
        height={1.5}
        position={[0, 0.25, 0.08]}
        alphaTest={0.06}
        depthWrite={false}
      />
      <mesh position={[0, -0.48, 0.02]} rotation-x={-Math.PI / 2}>
        <ringGeometry args={[0.28, playerMotion === "interact" ? 0.48 : 0.38, 36]} />
        <meshBasicMaterial
          color={playerMotion === "talk" ? "#d0b06b" : playerMotion === "interact" ? "#c89d52" : "#5f7890"}
          transparent
          opacity={playerMotion === "idle" ? 0.22 : 0.55}
        />
      </mesh>
    </group>
  );
}
