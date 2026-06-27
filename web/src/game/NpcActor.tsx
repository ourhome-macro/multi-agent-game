import type { ThreeEvent } from "@react-three/fiber";

import { getCharacterArt } from "../assets/artAssets";
import type { PublicCharacter } from "../types/public-api";
import type { CharacterPlacement } from "./layout";
import { SpritePlane } from "./SpritePlane";
import { TextSprite } from "./TextSprite";

type NpcActorProps = {
  character: PublicCharacter;
  placement: CharacterPlacement;
  enabled: boolean;
  selected: boolean;
  mode: "idle" | "talk";
  onHover: (id: string | null) => void;
  onSelect: () => void;
};

export function NpcActor({
  character,
  placement,
  enabled,
  selected,
  mode,
  onHover,
  onSelect,
}: NpcActorProps) {
  const art = getCharacterArt(character);
  const spriteHeight = character.id === "lin_qichi" ? 1.78 : 1.68;
  const spriteWidth = art ? (art.width / art.height) * spriteHeight : 0.58;

  const handleSelect = (event: ThreeEvent<MouseEvent>) => {
    event.stopPropagation();
    onSelect();
  };

  return (
    <group position={placement.position}>
      <mesh position={[0, -0.5, -0.02]} scale={[1.25, 0.28, 1]}>
        <circleGeometry args={[0.36, 32]} />
        <meshBasicMaterial color="#000000" transparent opacity={0.36} />
      </mesh>
      {art ? (
        <SpritePlane
          src={art.src}
          width={spriteWidth}
          height={spriteHeight}
          position={[0, 0.22, 0.05]}
          alphaTest={0.06}
          depthWrite={false}
        />
      ) : (
        <mesh position={[0, 0.2, 0.04]}>
          <planeGeometry args={[0.48, 1.2]} />
          <meshBasicMaterial color={placement.accent} transparent opacity={0.8} />
        </mesh>
      )}
      <mesh
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
        position={[0, 0.22, 0.08]}
      >
        <planeGeometry args={[Math.max(spriteWidth, 0.58), spriteHeight]} />
        <meshBasicMaterial color="#ffffff" transparent opacity={0.01} depthWrite={false} />
      </mesh>
      <mesh position={[0, -0.48, 0.02]} rotation-x={-Math.PI / 2}>
        <ringGeometry args={[0.32, selected ? 0.48 : 0.4, 36]} />
        <meshBasicMaterial
          color={mode === "talk" ? "#e1c06b" : selected ? "#d6b66f" : enabled ? "#b58b58" : "#6f665c"}
          transparent
          opacity={mode === "talk" || selected ? 0.68 : 0.28}
        />
      </mesh>
      <TextSprite
        text={character.display_name}
        position={[0, spriteHeight * 0.5 + 0.46, 0.12]}
        width={1.22}
        height={0.3}
        selected={selected}
        muted={!enabled}
      />
    </group>
  );
}
