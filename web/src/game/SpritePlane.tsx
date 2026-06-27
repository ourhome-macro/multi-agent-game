import { useLoader } from "@react-three/fiber";
import type { Vector3Tuple } from "three";
import * as THREE from "three";

type SpritePlaneProps = {
  src: string;
  width: number;
  height: number;
  position?: Vector3Tuple;
  opacity?: number;
  transparent?: boolean;
  alphaTest?: number;
  depthWrite?: boolean;
  renderOrder?: number;
};

export function SpritePlane({
  src,
  width,
  height,
  position = [0, 0, 0],
  opacity = 1,
  transparent = true,
  alphaTest = 0.001,
  depthWrite = true,
  renderOrder,
}: SpritePlaneProps) {
  const texture = useLoader(THREE.TextureLoader, src);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.generateMipmaps = false;
  texture.minFilter = THREE.LinearFilter;
  texture.magFilter = THREE.LinearFilter;
  texture.anisotropy = 8;
  texture.needsUpdate = true;

  return (
    <mesh position={position} renderOrder={renderOrder}>
      <planeGeometry args={[width, height]} />
      <meshBasicMaterial
        map={texture}
        transparent={transparent}
        opacity={opacity}
        alphaTest={transparent ? alphaTest : 0}
        depthWrite={depthWrite}
        side={THREE.DoubleSide}
        toneMapped={false}
      />
    </mesh>
  );
}
