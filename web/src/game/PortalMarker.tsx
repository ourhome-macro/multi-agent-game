import type { ThreeEvent } from "@react-three/fiber";

import type { ScenePortal } from "./layout";
import { TextSprite } from "./TextSprite";

type PortalMarkerProps = {
  portal: ScenePortal;
  busy: boolean;
  selected: boolean;
  onHover: (id: string | null) => void;
  onSelect: () => void;
};

export function PortalMarker({ portal, busy, selected, onHover, onSelect }: PortalMarkerProps) {
  const color = portal.direction === "up" ? "#8eb3c5" : portal.direction === "down" ? "#b5966a" : "#a98dbe";
  const arrow = portal.direction === "up" ? 1 : portal.direction === "down" ? -1 : 0;
  const handleSelect = (event: ThreeEvent<MouseEvent>) => {
    event.stopPropagation();
    if (!busy) onSelect();
  };
  const handleEnter = (event: ThreeEvent<PointerEvent>) => {
    event.stopPropagation();
    document.body.style.cursor = busy ? "not-allowed" : "pointer";
    onHover(portal.id);
  };
  const handleLeave = (event: ThreeEvent<PointerEvent>) => {
    event.stopPropagation();
    document.body.style.cursor = "";
    onHover(null);
  };

  return (
    <group
      position={portal.position}
      onClick={handleSelect}
      onPointerEnter={handleEnter}
      onPointerLeave={handleLeave}
    >
      <mesh position={[0, 0.2, 0]}>
        <planeGeometry args={[0.94, 2.16]} />
        <meshBasicMaterial color={color} transparent opacity={0.01} depthWrite={false} />
      </mesh>
      <mesh position={[0, 0.12 * arrow, 0.05]} rotation-z={arrow === 0 ? -Math.PI / 2 : 0}>
        <coneGeometry args={[0.2, 0.5, 3]} />
        <meshBasicMaterial color={color} transparent opacity={selected ? 0.92 : 0.64} />
      </mesh>
      <TextSprite text={portal.label} position={[0, 0.96, 0.08]} selected={selected} muted={busy} />
    </group>
  );
}
