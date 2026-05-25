// components/Profile.jsx
import { useState, useEffect } from "react";
import { exerciseApi } from "../api/exercise";
import "./UserAuth.css";

export default function Profile({ userId, onClose }) {
  const [formData, setFormData] = useState(null);
  const [isSaving, setIsSaving] = useState(false);

  const availableEquipments = ["哑铃", "弹力带", "杠铃", "壶铃", "泡沫轴", "瑜伽球", "辅助器械", "自重"];
  const injuryJoints = ["脊柱", "肩关节", "膝关节", "踝关节", "腕关节", "肘关节", "髋关节", "颈部", "肩胛带"];

  useEffect(() => {
    // 页面拉起时，倒查 MySQL 拿到当前的物理备份快照
    const fetchProfile = async () => {
      await exerciseApi.getProfile(userId)
      .then((data) => {
        // 将后端逗号分隔的纯字符串完美还原为前端的多选数组状态
        setFormData({
            ...data,
            equipments: data.equipments ? data.equipments.split(",") : [],
            injuries: data.injuries ? data.injuries.split(",") : []
        });
      })
    };
    fetchProfile();
  }, [userId]);

  const handleCheckboxChange = (field, value) => {
    setFormData(prev => {
      const current = prev[field];
      const updated = current.includes(value) ? current.filter(i => i !== value) : [...current, value];
      return { ...prev, [field]: updated };
    });
  };

  const handleSave = async (e) => {
    e.preventDefault();
    setIsSaving(true);

    const payload = {
      user_id: userId,
      username: formData.username,
      gender: formData.gender,
      weight_kg: parseFloat(formData.weight_kg).toFixed(2),
      height_cm: parseFloat(formData.height_cm).toFixed(2),
      fitness_level: formData.fitness_level,
      fitness_goal: formData.fitness_goal,
      equipments: formData.equipments.join(","), // 重新拍扁
      injuries: formData.injuries.join(",")      // 重新拍扁
    };

    await exerciseApi.updateProfile(payload)
    .then((data) => {
        if (data.status === "success") {
            alert("🎉 身体语义图谱钢印已动态演进升级！下一次提问将自动执行新法则拦截。");
            onClose();
        }
        setIsSaving(false);
    })
  }

  if (!formData) return <div className="profile-loading">正在反查解剖学图谱数据...</div>;

  return (
    <div className="profile-modal-overlay">
      <div className="auth-card profile-popup">
        <div className="profile-close-x" onClick={onClose}>×</div>
        <div className="auth-header">
          <h2>长效语义记忆修改中心</h2>
          <p>更新您的物理画像，中枢将实时同步演进 Neo4j 与 MySQL 的实体线</p>
        </div>
        <form onSubmit={handleSave} className="auth-form">
          {/* 复用 Signup 的表单行结构 */}
          <div className="form-row-grid tri-grid">
            <div className="form-group"><label>身高 (cm)</label><input type="number" value={formData.height_cm} onChange={e => setFormData({...formData, height_cm: e.target.value})} /></div>
            <div className="form-group"><label>体重 (kg)</label><input type="number" value={formData.weight_kg} onChange={e => setFormData({...formData, weight_kg: e.target.value})} /></div>
            <div className="form-group">
              <label>体能等级</label>
              <select value={formData.fitness_level} onChange={e => setFormData({...formData, fitness_level: e.target.value})}>
                <option value="beginner">初学者</option><option value="intermediate">进阶者</option><option value="advanced">高阶者</option>
              </select>
            </div>
          </div>
          
          <div className="form-group checkbox-section">
            <label>🛠️ 调整可用训练器械（直接锁死下一轮 SQL 提取范围）</label>
            <div className="checkbox-flex">
              {availableEquipments.map(eq => (
                <label key={eq} className={`checkbox-tag ${formData.equipments.includes(eq) ? "active" : ""}`}>
                  <input type="checkbox" checked={formData.equipments.includes(eq)} onChange={() => handleCheckboxChange("equipments", eq)} />{eq}
                </label>
              ))}
            </div>
          </div>

          <div className="form-group checkbox-section">
            <label>⚠️ 更新目前有痛感/拉伤的受损关节（直接物理拦截危险动作）</label>
            <div className="checkbox-flex">
              {injuryJoints.map(ij => (
                <label key={ij} className={`checkbox-tag injury-tag ${formData.injuries.includes(ij) ? "active" : ""}`}>
                  <input type="checkbox" checked={formData.injuries.includes(ij)} onChange={() => handleCheckboxChange("injuries", ij)} />{ij}
                </label>
              ))}
            </div>
          </div>
          <button type="submit" disabled={isSaving} className="auth-submit-btn">{isSaving ? "正在动态织入图谱..." : "保存修改并使新防线生效"}</button>
        </form>
      </div>
    </div>
  );
}
