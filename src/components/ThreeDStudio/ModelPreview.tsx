import { Suspense, useEffect, useMemo, useState } from "react";
import { Canvas, useThree } from "@react-three/fiber";
import {
  ContactShadows,
  Environment,
  Html,
  OrbitControls,
  useGLTF,
} from "@react-three/drei";
import { convertFileSrc } from "@tauri-apps/api/core";
import * as THREE from "three";
import Icon from "../Icon";
import { useLanguage } from "../../i18n";

const ENV_PRESETS = ["studio", "city", "warehouse", "sunset", "dawn", "night"] as const;
type EnvPreset = (typeof ENV_PRESETS)[number];
type ViewMode = "solid" | "wireframe";

const ENV_LABELS: Record<EnvPreset, [string, string]> = {
  studio: ["影棚", "Studio"],
  city: ["城市", "City"],
  warehouse: ["仓库", "Warehouse"],
  sunset: ["日落", "Sunset"],
  dawn: ["黎明", "Dawn"],
  night: ["夜景", "Night"],
};

function Model({ url, viewMode }: { url: string; viewMode: ViewMode }) {
  const { text } = useLanguage();
  const [error, setError] = useState(false);
  const { scene } = useGLTF(url, true, undefined, (e: unknown) => {
    console.error("GLTF load error:", e);
    setError(true);
  });

  const modified = useMemo(() => {
    const copy = scene.clone(true);
    copy.traverse((child) => {
      if (child instanceof THREE.Mesh && child.material) {
        const materials = (Array.isArray(child.material) ? child.material : [child.material]).map(
          (material) => material.clone(),
        );
        child.material = Array.isArray(child.material) ? materials : materials[0];
        materials.forEach((material) => {
          if (material instanceof THREE.MeshStandardMaterial) {
            material.wireframe = viewMode === "wireframe";
            if (viewMode === "wireframe") material.color.set("#2f6f82");
          }
        });
      }
    });

    const box = new THREE.Box3().setFromObject(copy);
    const center = box.getCenter(new THREE.Vector3());
    const size = box.getSize(new THREE.Vector3());
    const maxDim = Math.max(size.x, size.y, size.z);
    const scale = maxDim > 0 ? 4 / maxDim : 1;
    copy.position.set(-center.x * scale, -center.y * scale, -center.z * scale);
    copy.scale.setScalar(scale);
    return copy;
  }, [scene, viewMode]);

  if (error) {
    return (
      <Html center>
        <div style={{ color: "var(--text-muted)", textAlign: "center", fontSize: 12 }}>
          <Icon name="alert" size={24} />
          <div style={{ marginTop: 8 }}>{text("3D 模型加载失败", "Failed to load 3D model")}</div>
        </div>
      </Html>
    );
  }

  return <primitive object={modified} />;
}

function SceneContent({
  url,
  viewMode,
  envPreset,
  resetKey,
}: {
  url: string;
  viewMode: ViewMode;
  envPreset: EnvPreset;
  resetKey: number;
}) {
  const { camera } = useThree();
  const { text } = useLanguage();

  useEffect(() => {
    if (resetKey > 0) {
      camera.position.set(6, 4, 6);
      camera.lookAt(0, 0, 0);
    }
  }, [camera, resetKey]);

  return (
    <>
      <ambientLight intensity={0.42} />
      <directionalLight position={[10, 10, 5]} intensity={1.05} castShadow />
      <directionalLight position={[-5, 3, -5]} intensity={0.32} />
      <Suspense
        fallback={
          <Html center>
            <div style={{ color: "var(--text-muted)", fontSize: 13, textAlign: "center" }}>
              <div
                style={{
                  width: 38,
                  height: 38,
                  borderRadius: "50%",
                  border: "3px solid var(--bg-input)",
                  borderTopColor: "var(--accent-warm)",
                  animation: "spin 1s linear infinite",
                  margin: "0 auto 9px",
                }}
              />
              {text("加载模型", "Loading model")}
            </div>
          </Html>
        }
      >
        <Model url={url} viewMode={viewMode} />
        <Environment preset={envPreset} />
        <ContactShadows position={[0, -2, 0]} opacity={0.36} scale={10} blur={2.2} />
        <OrbitControls enableDamping dampingFactor={0.1} />
      </Suspense>
    </>
  );
}

export default function ModelPreview({
  modelPath,
  compact = false,
}: {
  modelPath: string | null;
  compact?: boolean;
}) {
  const { language, text } = useLanguage();
  const [viewMode, setViewMode] = useState<ViewMode>("solid");
  const [envPreset, setEnvPreset] = useState<EnvPreset>("studio");
  const [resetKey, setResetKey] = useState(0);

  if (!modelPath) return null;

  const url = convertFileSrc(modelPath);

  return (
    <div style={{ width: "100%", height: "100%", position: "relative" }}>
      <div
        style={{
          position: "absolute",
          top: 10,
          left: 10,
          right: 10,
          zIndex: 10,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          gap: 8,
          pointerEvents: "none",
        }}
      >
        <div className="segmented" style={{ pointerEvents: "auto", padding: 3, background: "rgba(255,254,250,0.78)" }}>
          <button className={`segment ${viewMode === "solid" ? "active" : ""}`} onClick={() => setViewMode("solid")}>
            {text("实体", "Solid")}
          </button>
          <button className={`segment ${viewMode === "wireframe" ? "active" : ""}`} onClick={() => setViewMode("wireframe")}>
            {text("线框", "Wireframe")}
          </button>
          <button className="segment" onClick={() => setResetKey((k) => k + 1)} title={text("重置视角", "Reset view")}>
            <Icon name="refresh" size={13} />
          </button>
          {!compact && (
            <button className="segment" onClick={() => navigator.clipboard.writeText(modelPath)} title={text("复制路径", "Copy path")}>
              <Icon name="copy" size={13} />
            </button>
          )}
        </div>

        {!compact && (
          <select
            value={envPreset}
            onChange={(e) => setEnvPreset(e.target.value as EnvPreset)}
            style={{
              height: 32,
              padding: "0 9px",
              borderRadius: 9,
              border: "1px solid var(--border-subtle)",
              background: "rgba(255,254,250,0.8)",
              color: "var(--text-secondary)",
              fontSize: 12,
              cursor: "pointer",
              outline: "none",
              pointerEvents: "auto",
            }}
          >
            {ENV_PRESETS.map((p) => (
              <option key={p} value={p}>
                {ENV_LABELS[p][language === "zh" ? 0 : 1]}
              </option>
            ))}
          </select>
        )}
      </div>

      <Canvas
        camera={{ position: [6, 4, 6], fov: 45 }}
        style={{
          background:
            "radial-gradient(circle at 50% 30%, rgba(255,254,250,0.98), rgba(238,236,230,0.94) 58%, rgba(222,216,201,0.9))",
          borderRadius: compact ? 0 : 16,
        }}
      >
        <SceneContent url={url} viewMode={viewMode} envPreset={envPreset} resetKey={resetKey} />
      </Canvas>
    </div>
  );
}
