type IntroOverlayProps = {
  visible: boolean;
  onContinue: () => void;
};

export function IntroOverlay({ visible, onContinue }: IntroOverlayProps) {
  if (!visible) return null;

  return (
    <div className="intro-overlay">
      <div className="intro-copy">
        <span className="intro-kicker">雾钟山庄 · 暴雨夜</span>
        <h1>你们不是来赴宴的。</h1>
        <div className="intro-pages">
          <p>
            一周前，山庄主人陆澜生分别寄出邀请函，召集四名与他有旧怨的人来到雾钟山庄。
          </p>
          <p>
            他声称今晚会公布新剧《回声钟》的最终署名、雾钟山庄与剧场股份的信托安排，
            以及一封与十年前江若岚坠湖旧案有关的信。
          </p>
          <p>
            邀请函背面写着同一句话：十一点十七分，钟会替我们作证。
          </p>
          <p>
            旧钟响起后，书房传来酒杯碎裂声。门被撞开时，陆澜生已经倒在反锁的书房里。
          </p>
        </div>
        <p className="intro-objective">
          雨封住山路，警方暂时无法抵达。你需要在雾散之前查清：这间密室到底是谁搭好的。
        </p>
      </div>
      <button type="button" onClick={onContinue}>
        进入雾钟山庄
      </button>
    </div>
  );
}
