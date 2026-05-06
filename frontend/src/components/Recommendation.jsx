import ExerciseCard from "./ExerciseCard";

export default function Recommendation({ data }) {
  if (!data) return null;

  return (
    <div className="space-y-6 mt-6 animate-fade-in">
      {/* AI 建议部分 */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-orange-50 p-4 rounded-xl border border-orange-100">
          <h4 className="font-bold text-orange-800 mb-2">🔥 热身建议</h4>
          <p className="text-sm text-orange-900 leading-relaxed">
            {data.warmup_tips}
          </p>
        </div>
        <div className="bg-red-50 p-4 rounded-xl border border-red-100">
          <h4 className="font-bold text-red-800 mb-2">⚠️ 安全防范</h4>
          <p className="text-sm text-red-900 leading-relaxed">
            {data.safety_notes}
          </p>
        </div>
      </div>

      {/* 动作列表 */}
      <div>
        <h4 className="font-bold text-gray-800 mb-4 px-1">推荐动作组合</h4>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {data.planned_exercises.map((ex) => (
            <ExerciseCard key={ex.id} exercise={ex} />
          ))}
        </div>
      </div>
    </div>
  );
}
