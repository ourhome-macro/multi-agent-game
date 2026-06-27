import { useEffect, useMemo } from "react";
import * as THREE from "three";

import type { Vec3 } from "./layout";

type TextSpriteProps = {
  text: string;
  position: Vec3;
  width?: number;
  height?: number;
  selected?: boolean;
  muted?: boolean;
};

export function TextSprite({
  text,
  position,
  width = 0.92,
  height = 0.24,
  selected = false,
  muted = false,
}: TextSpriteProps) {
  const texture = useMemo(() => makeTextTexture(text, selected, muted), [text, selected, muted]);

  useEffect(() => () => texture.dispose(), [texture]);

  return (
    <sprite position={position} scale={[width, height, 1]}>
      <spriteMaterial map={texture} transparent depthTest={false} depthWrite={false} />
    </sprite>
  );
}

function makeTextTexture(text: string, selected: boolean, muted: boolean): THREE.CanvasTexture {
  const canvas = document.createElement("canvas");
  canvas.width = 1024;
  canvas.height = 256;
  const context = canvas.getContext("2d");
  if (!context) return new THREE.CanvasTexture(canvas);

  context.clearRect(0, 0, canvas.width, canvas.height);
  context.font = '700 72px "Microsoft YaHei", "PingFang SC", "Segoe UI", sans-serif';
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.lineJoin = "round";
  context.miterLimit = 2;
  context.shadowColor = "rgba(0, 0, 0, 0.92)";
  context.shadowBlur = 4;
  context.shadowOffsetY = 1;
  context.strokeStyle = selected ? "rgba(54, 26, 12, 0.95)" : "rgba(0, 0, 0, 0.84)";
  context.lineWidth = selected ? 14 : 11;
  context.strokeText(trim(text, 12), 512, 128, 860);
  context.shadowBlur = 0;
  context.fillStyle = muted ? "#b7ad9d" : selected ? "#ffe0a6" : "#f5e4c6";
  context.fillText(trim(text, 12), 512, 128, 860);

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.generateMipmaps = false;
  texture.minFilter = THREE.LinearFilter;
  texture.magFilter = THREE.LinearFilter;
  texture.needsUpdate = true;
  return texture;
}

function trim(value: string, max: number): string {
  return value.length > max ? `${value.slice(0, max - 1)}...` : value;
}
