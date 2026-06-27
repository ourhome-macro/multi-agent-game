import { Canvas } from "@react-three/fiber";

import { SceneRenderer } from "./SceneRenderer";
import type {
  PlayerAction,
  PublicCaseDetail,
  PublicStateSummary,
  SessionAffordances,
} from "../types/public-api";

type GameCanvasProps = {
  caseDetail: PublicCaseDetail;
  state: PublicStateSummary | null;
  affordances: SessionAffordances | null;
  currentSceneId: string;
  busy: boolean;
  onAction: (action: PlayerAction) => void;
  onSound: (name: "hover" | "click" | "inspect" | "clue" | "dialogue" | "phase" | "error") => void;
};

export function GameCanvas(props: GameCanvasProps) {
  return (
    <div className="game-canvas-shell">
      <Canvas
        shadows
        orthographic
        dpr={2}
        camera={{ position: [0, 0.04, 8], zoom: 118, near: 0.1, far: 100 }}
        gl={{ antialias: true, alpha: false, preserveDrawingBuffer: true }}
      >
        <color attach="background" args={["#171513"]} />
        <fog attach="fog" args={["#171513", 6.5, 13]} />
        <SceneRenderer {...props} />
      </Canvas>
    </div>
  );
}
