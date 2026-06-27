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
  hovered: boolean;
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
  hovered,
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
        <planeGeometry args={[placement.size[0] * 1.25, placement.size[1] * 1.45]} />
        <meshBasicMaterial color="#ffffff" opacity={0.01} transparent depthWrite={false} />
      </mesh>
      <mesh position={[0, 0, 0.03]}>
        <ringGeometry args={[0.05, selected || hovered ? 0.13 : 0.09, 24]} />
        <meshBasicMaterial
          color={discovered ? "#8ccf93" : tone.glow}
          opacity={selected || hovered ? 0.76 : enabled ? 0.18 : 0.08}
          transparent
        />
      </mesh>
      <mesh position={[0, 0, 0.04]} rotation-z={Math.PI / 4}>
        <planeGeometry args={[selected || hovered ? 0.18 : 0.12, selected || hovered ? 0.18 : 0.12]} />
        <meshBasicMaterial
          color={discovered ? "#8ccf93" : tone.glow}
          transparent
          opacity={selected || hovered ? 0.18 : enabled ? 0.055 : 0.025}
          depthWrite={false}
        />
      </mesh>
      {selected || hovered ? (
        <TextSprite
          text={hotspot.name}
          position={[0, placement.size[1] + 0.25, 0.05]}
          selected={selected}
          muted={!enabled}
        />
      ) : null}
    </group>
  );
}
