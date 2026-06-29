import { useState } from "react";
import ExerciseCard from "./ExerciseCard";
import ExerciseModal from "./ExerciseModal";
import {
  useTypewriter,
} from "../hooks/useTypewriter";

export default function Recommendation({
  data,
  streaming = false,
  enriching = false,
  pipelineStatus = "",
}) {
  const [selectedEx, setSelectedEx] = useState("");

  const detailed_guidance = data?.detailed_guidance;
  const hasGuidance = Boolean(detailed_guidance?.trim());
  const showPipeline = streaming && !hasGuidance && Boolean(pipelineStatus);
  const typedPipeline = useTypewriter(pipelineStatus, {
    active: showPipeline,
    msPerChar: 16,
  });

  if (!data) return null;

  const {
    response_type,
    greeting,
    exercises,
    safety_alerts,
    summary,
    medical_disclaimer,
  } = data;

  const showGreeting = Boolean(greeting?.trim());
  const showSummary =
    Boolean(summary?.trim()) &&
    !streaming &&
    summary.trim() !== (detailed_guidance || "").trim().slice(0, summary.length);

  const guidanceBody = hasGuidance ? detailed_guidance : "";

  return (
    <div className="space-y-6 mt-6 animate-fade-in">
      {showPipeline && (
        <p className="pipeline-status-line" aria-live="polite">
          {typedPipeline}
          <span className="streaming-cursor">▍</span>
        </p>
      )}

      {(hasGuidance || enriching || !streaming) && (
      <>
      {showGreeting && (
        <div className="px-1">
          <p className="text-gray-700 font-medium">{greeting}</p>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-orange-50 p-4 rounded-xl border border-orange-100">
          <h4 className="font-bold text-orange-800 mb-2">
            {response_type === "knowledge" ? "💡 深度指导" : "🔥 训练建议"}
          </h4>
          <p className="text-sm text-orange-900 leading-relaxed whitespace-pre-wrap">
            {guidanceBody}
            {streaming && hasGuidance && (
              <span className="streaming-cursor">▍</span>
            )}
          </p>
          {showSummary && (
            <div className="mt-3 pt-3 border-t border-orange-200/60">
              <p className="text-xs font-semibold text-orange-700 mb-1">
                一句话总结
              </p>
              <p className="text-sm text-orange-900 leading-relaxed whitespace-pre-wrap">
                {summary}
              </p>
            </div>
          )}
        </div>

        <div className="bg-red-50 p-4 rounded-xl border border-red-100">
          <h4 className="font-bold text-red-800 mb-2">⚠️ 安全防范</h4>
          <div className="text-sm text-red-900 leading-relaxed space-y-1">
            {enriching && (!safety_alerts || safety_alerts.length === 0) && (
              <p className="text-red-700/70 animate-pulse">正在生成安全提示…</p>
            )}
            {safety_alerts && safety_alerts.length > 0 ? (
              safety_alerts.map((alert, i) => <p key={i}>• {alert}</p>)
            ) : (
              !enriching && <p>暂无特定风险，请保持标准姿态。</p>
            )}
          </div>
        </div>
      </div>

      {enriching && (!exercises || exercises.length === 0) && (
        <p className="text-sm text-gray-500 px-1 animate-pulse">
          正在加载推荐动作卡片…
        </p>
      )}

      {exercises?.length > 0 && (
        <div>
          <h4 className="font-bold text-gray-800 mb-4 px-1">推荐动作组合</h4>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {exercises.map((ex) => (
              <ExerciseCard
                key={ex.id}
                exercise={ex}
                onClick={(exercise) => setSelectedEx(exercise)}
              />
            ))}
          </div>
        </div>
      )}

      {selectedEx && (
        <ExerciseModal
          exercise={selectedEx}
          onClose={() => setSelectedEx(null)}
        />
      )}

      {!streaming && (
        <div className="px-1 pt-2 border-t border-gray-50">
          <p className="text-[10px] text-gray-400 italic">
            {medical_disclaimer ||
              "以上建议仅供参考，如需获取医疗建议或诊断信息，请咨询专业人士。"}
          </p>
        </div>
      )}
      </>
      )}
    </div>
  );
}
