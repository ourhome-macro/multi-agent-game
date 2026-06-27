import { useEffect, useRef } from "react";

import { useUiStore } from "../state/uiStore";

const movementKeys = new Map([
  ["KeyW", { x: 0, y: 1 }],
  ["KeyA", { x: -1, y: 0 }],
  ["KeyS", { x: 0, y: -1 }],
  ["KeyD", { x: 1, y: 0 }],
]);

export function KeyboardController() {
  const pressedRef = useRef(new Set<string>());
  const setKeyboardVector = useUiStore((store) => store.setKeyboardVector);
  const clearSelection = useUiStore((store) => store.clearSelection);

  useEffect(() => {
    const publishVector = () => {
      let x = 0;
      let y = 0;
      pressedRef.current.forEach((code) => {
        const vector = movementKeys.get(code);
        if (!vector) return;
        x += vector.x;
        y += vector.y;
      });
      setKeyboardVector({ x: Math.sign(x), y: Math.sign(y) });
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (!movementKeys.has(event.code) || isEditableTarget(event.target)) return;
      event.preventDefault();
      pressedRef.current.add(event.code);
      clearSelection();
      publishVector();
    };

    const handleKeyUp = (event: KeyboardEvent) => {
      if (!movementKeys.has(event.code)) return;
      pressedRef.current.delete(event.code);
      publishVector();
    };

    const handleBlur = () => {
      pressedRef.current.clear();
      publishVector();
    };

    window.addEventListener("keydown", handleKeyDown);
    window.addEventListener("keyup", handleKeyUp);
    window.addEventListener("blur", handleBlur);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      window.removeEventListener("keyup", handleKeyUp);
      window.removeEventListener("blur", handleBlur);
    };
  }, [clearSelection, setKeyboardVector]);

  return null;
}

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tagName = target.tagName.toLowerCase();
  return tagName === "input" || tagName === "textarea" || tagName === "select" || target.isContentEditable;
}
