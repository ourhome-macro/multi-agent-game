import { useMemo } from "react";

type RoomSceneProps = {
  sceneId: string;
};

const scenePalette: Record<string, { wall: string; floor: string; accent: string; light: string }> = {
  study: { wall: "#2b2420", floor: "#30291f", accent: "#8f5a46", light: "#d2a66a" },
  clock_tower: { wall: "#242723", floor: "#252b25", accent: "#9a7a3f", light: "#b5a16b" },
  gallery: { wall: "#2b2428", floor: "#2d2924", accent: "#7d6a50", light: "#c9b58d" },
};

export function RoomScene({ sceneId }: RoomSceneProps) {
  const palette = useMemo(() => scenePalette[sceneId] || scenePalette.study, [sceneId]);

  return (
    <>
      <ambientLight intensity={0.42} />
      <directionalLight
        castShadow
        position={[2.8, 5.8, 2.4]}
        intensity={1.25}
        color={palette.light}
        shadow-mapSize={[1024, 1024]}
      />
      <pointLight position={[-2.4, 1.8, -1.2]} intensity={0.85} color={palette.accent} />

      <mesh receiveShadow rotation-x={-Math.PI / 2} position={[0, 0, 0]}>
        <planeGeometry args={[7.6, 5.4]} />
        <meshStandardMaterial color={palette.floor} roughness={0.92} metalness={0.04} />
      </mesh>
      <mesh receiveShadow position={[0, 1.42, -2.72]}>
        <boxGeometry args={[7.6, 2.84, 0.16]} />
        <meshStandardMaterial color={palette.wall} roughness={0.88} />
      </mesh>
      <mesh receiveShadow position={[-3.88, 1.18, 0]} rotation-y={Math.PI / 2}>
        <boxGeometry args={[5.4, 2.36, 0.16]} />
        <meshStandardMaterial color={palette.wall} roughness={0.9} />
      </mesh>
      <mesh receiveShadow position={[3.88, 1.18, 0]} rotation-y={Math.PI / 2}>
        <boxGeometry args={[5.4, 2.36, 0.16]} />
        <meshStandardMaterial color={palette.wall} roughness={0.9} />
      </mesh>

      <mesh castShadow receiveShadow position={[0, 0.18, -1.16]}>
        <boxGeometry args={[2.2, 0.36, 1.05]} />
        <meshStandardMaterial color="#4b3327" roughness={0.72} />
      </mesh>
      <mesh castShadow receiveShadow position={[2.5, 0.24, 1.08]}>
        <boxGeometry args={[1.12, 0.48, 0.82]} />
        <meshStandardMaterial color="#392822" roughness={0.96} />
      </mesh>
      <mesh castShadow receiveShadow position={[-2.58, 0.2, -0.98]}>
        <cylinderGeometry args={[0.54, 0.62, 0.32, 18]} />
        <meshStandardMaterial color="#493228" roughness={0.75} />
      </mesh>

      {Array.from({ length: 9 }, (_, index) => (
        <mesh key={`grid-x-${index}`} position={[-3.6 + index * 0.9, 0.018, 0]} rotation-x={-Math.PI / 2}>
          <planeGeometry args={[0.012, 5.2]} />
          <meshBasicMaterial color="#51473b" transparent opacity={0.32} />
        </mesh>
      ))}
      {Array.from({ length: 7 }, (_, index) => (
        <mesh key={`grid-z-${index}`} position={[0, 0.02, -2.6 + index * 0.86]} rotation-x={-Math.PI / 2}>
          <planeGeometry args={[7.2, 0.012]} />
          <meshBasicMaterial color="#51473b" transparent opacity={0.32} />
        </mesh>
      ))}
    </>
  );
}
