import { useState } from "react";
import DetailedGuidance from "./DetailedGuidance";
import ExerciseCard from "./ExerciseCard";
import ExerciseModal from "./ExerciseModal"

export default function Recommendation({ data }) {
    const [selectedEx, setSelectedEx] = useState("");
    if (!data) return null;

    // 解构后端 CoachResponse 模型
    const {
        response_type,
        greeting,
        exercises,
        detailed_guidance,
        safety_alerts,
        summary,
        medical_disclaimer
    } = data;

    return (
        <div className="space-y-6 mt-6 animate-fade-in">
            {/* 1. 开场欢迎语 */}
            <div className="px-1">
                <p className="text-gray-700 font-medium">{greeting}</p>
            </div>

            {/* 2. 核心建议与安全区 (复用之前的双栏风格) */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {/* 指导/热身区：根据 response_type 动态展示 */}
                <div className="bg-orange-50 p-4 rounded-xl border border-orange-100">
                    <h4 className="font-bold text-orange-800 mb-2">
                        {response_type === "knowledge" ? "💡 深度指导" : "🔥 训练建议"}
                    </h4>
                    <p text-sm text-orange-900 leading-relaxed whitespace-pre-wrap>
                        {detailed_guidance}
                    </p>
                    {/* <DetailedGuidance detailed_guidance={detailed_guidance}/> */}
                    <p className="text-sm text-orange-900 leading-relaxed whitespace-pre-wrap">
                        {summary}
                    </p>
                </div>

                {/* 安全区：展示所有的 safety_alerts */}
                <div className="bg-red-50 p-4 rounded-xl border border-red-100">
                    <h4 className="font-bold text-red-800 mb-2">⚠️ 安全防范</h4>
                    <div className="text-sm text-red-900 leading-relaxed space-y-1">
                        {safety_alerts && safety_alerts.length > 0 ? (
                            safety_alerts.map((alert, i) => <p key={i}>• {alert}</p>)
                        ) : (
                            <p>暂无特定风险，请保持标准姿态。</p>
                        )}
                    </div>
                </div>
            </div>

            {/* 3. 动作列表部分 (仅在有动作时渲染) */}
            {exercises?.length > 0 && (
                <div>
                    <h4 className="font-bold text-gray-800 mb-4 px-1">推荐动作组合</h4>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                        {data.exercises.map((ex) => (
                            <ExerciseCard
                                key={ex.id}
                                exercise={ex}
                                onClick={(ex) => setSelectedEx(ex)}
                            />
                        ))}
                    </div>
                </div>
            )}

            {/* 渲染 Modal，直接传入选中的 exercise 数据 */}
            {selectedEx && (
                <ExerciseModal
                    exercise={selectedEx}
                    onClose={() => setSelectedEx(null)}
                />
            )}

            {/* 4. 页脚免责声明 */}
            <div className="px-1 pt-2 border-t border-gray-50">
                <p className="text-[10px] text-gray-400 italic">
                    {medical_disclaimer}
                </p>
            </div>
        </div>
    );
}
