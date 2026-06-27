import type { ThreeEvent } from "@react-three/fiber";

import type { CharacterPlacement } from "./layout";
import { TextSprite } from "./TextSprite";
import type { PublicCharacter } from "../types/public-api";

type NpcActorProps = {
  character: PublicCharacter;
  placement: CharacterPlacement;
  enabled: boolean;
  selected: boolean;
  onHover: (id: string | null) => void;
  onSelect: () => void;
};

export function NpcActor({
  character,
  placement,
  enabled,
  selected,
  onHover,
  onSelect,
}: NpcActorProps) {
  const handleSelect = (event: ThreeEvent<MouseEvent>) => {
    event.stopPropagation();
    onSelect();
  };

  return (
    <group position={placement.position}>
      <mesh
        castShadow
        onClick={handleSelect}
        onPointerEnter={(event) => {
          event.stopPropagation();
          document.body.style.cursor = enabled ? "pointer" : "not-allowed";
          onHover(character.id);
        }}
        onPointerLeave={(event) => {
          event.stopPropagation();
          document.body.style.cursor = "";
          onHover(null);
        }}
      >
        <capsuleGeometry args={[0.24, 0.82, 6, 14]} />
        <meshStandardMaterial
          color={placement.accent}
          emissive={placement.accent}
          emissiveIntensity={selected ? 0.24 : 0.06}
          roughness={0.62}
        />
      </mesh>
      <mesh position={[0, 0.68, 0]}>
        <sphereGeometry args={[0.23, 20, 16]} />
        <meshStandardMaterial color="#d7c3a4" roughness={0.76} />
      </mesh>
      <mesh position={[0, -0.48, 0]} rotation-x={-Math.PI / 2}>
        <ringGeometry args={[0.32, selected ? 0.47 : 0.39, 36]} />
        <meshBasicMaterial
          color={selected ? "#e1c06b" : enabled ? "#b58b58" : "#6f665c"}
          transparent
          opacity={selected ? 0.72 : 0.36}
        />
      </mesh>
      <TextSprite
        text={character.display_name}
        position={[0, 1.24, 0]}
        width={1.1}
        selected={selected}
        muted={!enabled}
      />
    </group>
  );
}
