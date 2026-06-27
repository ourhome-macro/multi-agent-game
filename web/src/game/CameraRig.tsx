import { useFrame, useThree } from "@react-three/fiber";
import * as THREE from "three";

type CameraRigProps = {
  playerX: number;
  playerY: number;
};

const target = new THREE.Vector3();

export function CameraRig({ playerX, playerY }: CameraRigProps) {
  const camera = useThree((state) => state.camera);

  useFrame(() => {
    const clampedX = THREE.MathUtils.clamp(playerX, -1.2, 1.2);
    const clampedY = THREE.MathUtils.clamp((playerY + 1.08) * 0.35 + 0.04, -0.08, 0.18);
    target.set(clampedX, clampedY, 8);
    camera.position.lerp(target, 0.08);
    camera.lookAt(clampedX, clampedY - 0.04, 0);
  });

  return null;
}
