import { useEffect, useCallback, useState } from "react";
import { exerciseApi } from "../api/exercise";

const API_BASE_URL = process.env.REACT_APP_API_BASE_URL || "http://localhost:8000";

export default function ExerciseModal({ exercise, onClose }) {
  // 定义状态：存储从后端获取的完整详情、加载状态和错误状态
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [imageError, setImageError] = useState(false);

  useEffect(() => {
    setImageError(false);
  }, [exercise?.id]);

  // 处理背景点击关闭
  const handleBackdropClick = useCallback(
    (e) => {
      if (e.target === e.currentTarget) onClose();
    },
    [onClose],
  );

  // 处理 ESC 键关闭
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // 当组件挂载或 exercise.id 改变时，立即请求后端 API
  useEffect(() => {
    if (!exercise?.id) return;

    let isMounted = true; // 防止组件卸载后继续设置状态导致内存泄漏
    setLoading(true);
    setError(null);

    exerciseApi.getExerciseDetail(exercise.id)
      .then((data) => {
        if (isMounted) {
          setDetail(data);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (isMounted) {
          setError(err.message);
          setLoading(false);
        }
      });

    return () => {
      isMounted = false;
    };
  }, [exercise?.id]);

  if (!exercise) return null;

  // 优先使用 API 返回的详情数据，若还未加载完成则降级使用列表传入的基础数据
  const currentData = detail || exercise;
  const difficulty = currentData.difficulty?.toLowerCase() ?? "";

  return (
    <div className="modal-backdrop" onClick={handleBackdropClick}>
      <div className="modal-panel animate-slide-up" role="dialog" aria-modal="true">
        <div className="modal-header">
          {/* 标题可以直接用基础数据，避免等待闪烁 */}
          <h2 className="modal-title">{exercise.name_zh}</h2>
          <button className="modal-close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>

        <div className="modal-body">
          {/* 1. 加载中状态 */}
          {loading && (
            <div className="modal-loading-skeleton py-8 text-center text-gray-500">
              <div className="animate-spin inline-block w-6 h-6 border-[3px] border-current border-t-transparent text-blue-600 rounded-full mb-2"></div>
              <p>正在获取教练标准动作指南...</p>
            </div>
          )}

          {/* 2. 错误处理状态 */}
          {error && (
            <div className="modal-error bg-red-50 p-4 rounded-lg text-red-700 text-sm my-4">
              ⚠️ 获取失败: {error}。请稍后重试。
            </div>
          )}

          {/* 3. 数据渲染区（当 detail 存在时展现） */}
          {!loading && !error && (
            <>
              {/* 元数据标签区 */}
              <div className="modal-meta">
                {difficulty && (
                  <span className={`meta-tag difficulty ${difficulty}`}>
                    {difficulty}
                  </span>
                )}
                {currentData.body_part_zh && (
                  <span className="meta-tag">{currentData.body_part_zh}</span>
                )}
                <span className="meta-tag">{currentData.target_zh}</span>
                <span className="meta-tag">{currentData.equipment_zh}</span>
              </div>

              {/* 动态加入：新架构中数据库存储的 GIF 演示图 */}
              {currentData.gif_path && (
                <div className="modal-media-wrapper my-4 overflow-hidden rounded-lg border border-gray-100 bg-gray-50 flex justify-center">
                  {!imageError ? (
                    <img
                      src={`${API_BASE_URL}${currentData.gif_path}`}
                      alt={currentData.name_zh}
                      className="max-h-64 object-contain rounded"
                      onError={() => setImageError(true)}
                    />
                  ) : (
                    /* 优雅降级：当动图找不到时展示的占位 UI */
                    <div className="flex flex-col items-center justify-center py-8 text-gray-400 select-none">
                      <span className="text-3xl mb-2">🏋️‍♂️</span>
                      <p className="text-xs font-medium text-gray-500">
                        暂无动图演示，请参考下方文字步骤
                      </p>
                    </div>
                  )}
                </div>
              )}

              {/* 动作描述 */}
              {currentData.description_zh && (
                <div>
                  <p className="modal-section-title">关于此动作</p>
                  <p className="modal-description">{currentData.description_zh}</p>
                </div>
              )}

              {/* 核心步骤 - 稳定渲染自数据库的 JSON 数组 */}
              {currentData.instructions_zh?.length > 0 && (
                <div>
                  <p className="modal-section-title">执行步骤</p>
                  <ol className="instructions-list">
                    {currentData.instructions_zh.map((step, i) => (
                      <li key={i} className="instruction-step">
                        <span className="step-number">{i + 1}</span>
                        <span className="step-text">{step}</span>
                      </li>
                    ))}
                  </ol>
                </div>
              )}

              {/* 发力感口令 (如果你将发力感维护在副目标肌群或说明中) */}
              {currentData.secondary_muscles_zh?.length > 0 && (
                <div className="bg-blue-50 p-4 rounded-lg mt-4 border border-blue-100">
                  <p className="modal-section-title text-blue-800">协同参与肌群</p>
                  <div className="modal-meta">
                    {currentData.secondary_muscles_zh.map((muscle, i) => (
                      <span key={i} className="meta-tag">
                        {muscle}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
