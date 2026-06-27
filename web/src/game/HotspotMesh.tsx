import type { ThreeEvent } from "@react-three/fiber";

import type { HotspotPlacement } from "./layout";
import { TextSprite } from "./TextSprite";
import type { PublicSceneHotspot } from "../types/public-api";

type HotspotMeshProps = {
  hotspot: PublicSceneHotspot;
  placement: HotspotPlacement;
  enabled: boolean;
  discovered: boolean;
  selected: boolean;
  onHover: (id: string | null) => void;
  onSelect: () => void;
};

const tones: Record<HotspotPlacement["tone"], { surface: string; glow: string }> = {
  wine: { surface: "#7b363c", glow: "#d47777" },
  brass: { surface: "#9b7a42", glow: "#e3bc73" },
  paper: { surface: "#b2a27d", glow: "#f0ddb3" },
  medicine: { surface: "#678b78", glow: "#a3d3b9" },
  power: { surface: "#607f91", glow: "#9fcde4" },
  stone: { surface: "#77706a", glow: "#c3bbb2" },
};

export function HotspotMesh({
  hotspot,
  placement,
  enabled,
  discovered,
  selected,
  onHover,
  onSelect,
}: HotspotMeshProps) {
  const tone = tones[placement.tone];

  const handlePointer = (event: ThreeEvent<MouseEvent>) => {
    event.stopPropagation();
    onSelect();
  };

  return (
    <group position={placement.position}>
      <mesh
        castShadow
        receiveShadow
        onClick={handlePointer}
        onPointerEnter={(event) => {
          event.stopPropagation();
          document.body.style.cursor = enabled ? "pointer" : "not-allowed";
          onHover(hotspot.id);
        }}
        onPointerLeave={(event) => {
          event.stopPropagation();
          document.body.style.cursor = "";
          onHover(null);
        }}
      >
        <boxGeometry args={placement.size} />
        <meshStandardMaterial
          color={tone.surface}
          emissive={tone.glow}
          emissiveIntensity={selected ? 0.22 : enabled ? 0.08 : 0.015}
          opacity={enabled ? 0.86 : 0.42}
          transparent
          roughness={0.68}
          metalness={placement.tone === "brass" ? 0.2 : 0.04}
        />
      </mesh>
      <mesh position={[0, -placement.size[1] * 0.42, 0]} rotation-x={-Math.PI / 2}>
        <ringGeometry args={[0.34, selected ? 0.42 : 0.38, 36]} />
        <meshBasicMaterial
          color={discovered ? "#7fb884" : tone.glow}
          transparent
          opacity={enabled || selected ? 0.62 : 0.18}
        />
      </mesh>
      <TextSprite
        text={hotspot.name}
        position={[0, placement.size[1] + 0.32, 0]}
        selected={selected}
        muted={!enabled}
      />
    </group>
  );
}
