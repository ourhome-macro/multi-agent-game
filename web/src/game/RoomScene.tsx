import { sceneArtById } from "../assets/artAssets";
import { SpritePlane } from "./SpritePlane";

type RoomSceneProps = {
  sceneId: string;
};

const sceneFrame: Record<string, { width: number; height: number; y: number }> = {
  study: { width: 11.55, height: 4.07, y: 0.2 },
  gallery: { width: 11.55, height: 3.59, y: 0.14 },
  clock_tower: { width: 11.55, height: 4.15, y: 0.04 },
};

export function RoomScene({ sceneId }: RoomSceneProps) {
  const art = sceneArtById[sceneId] || sceneArtById.study;
  const frame = sceneFrame[sceneId] || sceneFrame.study;

  return (
    <>
      <ambientLight intensity={0.9} />
      <directionalLight position={[0, 4.2, 4]} intensity={0.58} color="#f2d5a0" />

      <mesh position={[0, 0.02, -1.36]}>
        <planeGeometry args={[12.8, 6.9]} />
        <meshBasicMaterial color="#050505" />
      </mesh>
      <SpritePlane
        src={art.src}
        width={frame.width}
        height={frame.height}
        position={[0, frame.y, -1.18]}
        transparent={false}
        alphaTest={0}
      />
      <mesh position={[0, -1.53, -1.05]}>
        <planeGeometry args={[12.4, 0.62]} />
        <meshBasicMaterial color="#020202" transparent opacity={0.2} />
      </mesh>
    </>
  );
}
