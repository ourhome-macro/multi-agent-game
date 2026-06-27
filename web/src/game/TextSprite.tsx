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
  width = 1.18,
  height = 0.32,
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
  canvas.width = 512;
  canvas.height = 144;
  const context = canvas.getContext("2d");
  if (!context) return new THREE.CanvasTexture(canvas);

  const background = selected ? "rgba(92, 65, 33, 0.92)" : "rgba(28, 25, 22, 0.86)";
  const border = selected ? "rgba(222, 184, 105, 0.96)" : "rgba(232, 210, 172, 0.48)";
  const color = muted ? "#a59a8a" : "#f3dfbd";

  roundRect(context, 18, 18, 476, 108, 18);
  context.fillStyle = background;
  context.fill();
  context.strokeStyle = border;
  context.lineWidth = 4;
  context.stroke();

  context.fillStyle = color;
  context.font =
    '500 38px "Microsoft YaHei", "PingFang SC", "Segoe UI", sans-serif';
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.fillText(trim(text, 12), 256, 72, 430);

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.needsUpdate = true;
  return texture;
}

function roundRect(
  context: CanvasRenderingContext2D,
  x: number,
  y: number,
  width: number,
  height: number,
  radius: number,
) {
  context.beginPath();
  context.moveTo(x + radius, y);
  context.lineTo(x + width - radius, y);
  context.quadraticCurveTo(x + width, y, x + width, y + radius);
  context.lineTo(x + width, y + height - radius);
  context.quadraticCurveTo(x + width, y + height, x + width - radius, y + height);
  context.lineTo(x + radius, y + height);
  context.quadraticCurveTo(x, y + height, x, y + height - radius);
  context.lineTo(x, y + radius);
  context.quadraticCurveTo(x, y, x + radius, y);
  context.closePath();
}

function trim(value: string, max: number): string {
  return value.length > max ? `${value.slice(0, max - 1)}…` : value;
}
