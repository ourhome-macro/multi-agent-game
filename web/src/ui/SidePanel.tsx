import { FileText, NotebookTabs, ScrollText } from "lucide-react";

import { getClueImage } from "../assets/artAssets";
import { useUiStore } from "../state/uiStore";
import type {
  PublicCaseDetail,
  PublicScene,
  PublicStateSummary,
} from "../types/public-api";

type SidePanelProps = {
  caseDetail: PublicCaseDetail;
  scene: PublicScene;
  state: PublicStateSummary | null;
  open: boolean;
  onClose: () => void;
};

export function SidePanel({ caseDetail, scene, state, open, onClose }: SidePanelProps) {
  const activePanel = useUiStore((store) => store.activePanel);
  const setActivePanel = useUiStore((store) => store.setActivePanel);

  return (
    <aside className={`side-panel ${open ? "is-open" : ""}`}>
      <div className="panel-tabs">
        <button
          className={activePanel === "story" ? "is-active" : ""}
          type="button"
          title="目前知晓"
          onClick={() => setActivePanel("story")}
        >
          <ScrollText size={17} />
        </button>
        <button
          className={activePanel === "case" ? "is-active" : ""}
          type="button"
          title="案件"
          onClick={() => setActivePanel("case")}
        >
          <NotebookTabs size={17} />
        </button>
        <button
          className={activePanel === "evidence" ? "is-active" : ""}
          type="button"
          title="证据"
          onClick={() => setActivePanel("evidence")}
        >
          <FileText size={17} />
        </button>
        <button type="button" title="关闭" onClick={onClose}>
          ×
        </button>
      </div>
      <div className="panel-body">
        {activePanel === "story" ? <StoryPanel state={state} /> : null}
        {activePanel === "case" ? (
          <CasePanel caseDetail={caseDetail} scene={scene} />
        ) : null}
        {activePanel === "evidence" ? <EvidencePanel state={state} /> : null}
      </div>
    </aside>
  );
}

function StoryPanel({ state }: { state: PublicStateSummary | null }) {
  const knowledge = state?.player_knowledge || [];
  return (
    <section className="panel-section story-panel">
      <h2>目前知晓的剧情</h2>
      <div className="story-stack">
        <article className="story-item">
          <strong>召集理由</strong>
          <p>
            陆澜生一周前发出邀请函，要求众人暴雨夜来到雾钟山庄。他说要公布《回声钟》的最终署名、
            山庄与剧场股份的信托安排，以及一封牵涉十年前江若岚坠湖旧案的信。
          </p>
        </article>
        <article className="story-item">
          <strong>邀请函</strong>
          <p>每封邀请函背面都写着：十一点十七分，钟会替我们作证。</p>
        </article>
        <article className="story-item">
          <strong>案发现场</strong>
          <p>
            旧钟响起后，书房传出酒杯碎裂声。众人撞门进入时，陆澜生已经死亡；门从内侧反锁，
            窗扣闭合，怀表停在二十三点十七分，桌边留下红酒与烧毁信纸。
          </p>
        </article>
        <article className="story-item">
          <strong>当前目标</strong>
          <p>
            在警方抵达前，确认密室是否成立，查清红酒、门锁、录音、怀表和烧毁信纸之间的关系，
            并弄清每个到场者今晚真正想从陆澜生那里得到什么。
          </p>
        </article>
      </div>
      <h3>调查新增</h3>
      {knowledge.length === 0 ? <p className="empty-text">尚未形成新的可靠叙事线索。</p> : null}
      <div className="knowledge-stack">
        {knowledge.map((item) => (
          <article key={`${item.clue_id || item.title}-${item.title}`} className="knowledge-item">
            <strong>{item.title}</strong>
            <p>{item.summary}</p>
          </article>
        ))}
      </div>
    </section>
  );
}

function CasePanel({
  caseDetail,
  scene,
}: {
  caseDetail: PublicCaseDetail;
  scene: PublicScene;
}) {
  return (
    <section className="panel-section">
      <h2>{caseDetail.title}</h2>
      <p>{caseDetail.description}</p>
      <h3>{scene.name}</h3>
      <p>{scene.description}</p>
      <div className="compact-list">
        {scene.hotspots.map((hotspot) => (
          <span key={hotspot.id}>{hotspot.name}</span>
        ))}
      </div>
    </section>
  );
}

function EvidencePanel({ state }: { state: PublicStateSummary | null }) {
  const evidence = state?.evidence_assets || [];
  const knowledge = state?.player_knowledge || [];
  return (
    <section className="panel-section">
      <h2>证据板</h2>
      {evidence.length === 0 ? <p className="empty-text">尚未形成可展示证据。</p> : null}
      <div className="evidence-stack">
        {evidence.map((item) => {
          const clueImage = getClueImage(item.clue_id || item.id);
          return (
            <article key={item.id} className="evidence-item">
              {clueImage ? <img src={clueImage} alt={item.title} className="evidence-thumb" /> : null}
              <div>
                <strong>{item.title}</strong>
                <p>{item.summary}</p>
              </div>
            </article>
          );
        })}
      </div>
      <h3>已记下</h3>
      <div className="knowledge-stack">
        {knowledge.map((item) => (
          <article key={`${item.clue_id || item.title}-${item.title}`} className="knowledge-item">
            <strong>{item.title}</strong>
            <p>{item.summary}</p>
          </article>
        ))}
      </div>
    </section>
  );
}
