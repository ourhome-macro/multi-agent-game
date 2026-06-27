import { Map } from "lucide-react";

import type { PublicScene } from "../types/public-api";

type SceneTabsProps = {
  scenes: PublicScene[];
  currentSceneId: string;
  onChange: (sceneId: string) => void;
};

export function SceneTabs({ scenes, currentSceneId, onChange }: SceneTabsProps) {
  return (
    <nav className="scene-tabs" aria-label="场景">
      <Map size={17} aria-hidden />
      {scenes.map((scene) => (
        <button
          key={scene.id}
          className={scene.id === currentSceneId ? "is-active" : ""}
          type="button"
          title={scene.description || scene.name}
          onClick={() => onChange(scene.id)}
        >
          {scene.name}
        </button>
      ))}
    </nav>
  );
}
