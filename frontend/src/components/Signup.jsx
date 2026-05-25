// components/Signup.jsx
import { useState } from "react";
import { exerciseApi } from "../api/exercise";
import "./UserAuth.css"; // 共享的高端钢蓝文风样式

export default function Signup({ onAuthSuccess }) {
    const [formData, setFormData] = useState({
        username: "",
        password: "", // 物理注册必填
        gender: "male",
        weight_kg: "70.00",
        height_cm: "175.00",
        fitness_level: "beginner",
        fitness_goal: "增肌",
        equipments: [], // 以数组暂存，最后合并为逗号开的纯字符串
        injuries: []
    });

    const [error, setError] = useState("");

    const availableEquipments = ["哑铃", "弹力带", "杠铃", "壶铃", "泡沫轴", "瑜伽球", "辅助器械", "自重"];
    const injuryJoints = ["脊柱", "肩关节", "膝关节", "踝关节", "腕关节", "肘关节", "髋关节", "颈部", "肩胛带"];

    const handleCheckboxChange = (field, value) => {
        setFormData(prev => {
            const current = prev[field];
            const updated = current.includes(value)
                ? current.filter(item => item !== value)
                : [...current, value];
            return { ...prev, [field]: updated };
        });
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        setError("");

        const payload = {
            username: formData.username,
            password: formData.password,
            gender: formData.gender,
            weight_kg: Number(parseFloat(formData.weight_kg).toFixed(2)), // 强对齐 Decimal(5,2)
            height_cm: Number(parseFloat(formData.height_cm).toFixed(2)),
            fitness_level: formData.fitness_level,
            fitness_goal: formData.fitness_goal,
            equipments: formData.equipments.length > 0 ? formData.equipments.join(",") : "自重",
            injuries: formData.injuries.length > 0 ? formData.injuries.join(",") : ""
        };

        try {
            await exerciseApi.signup(payload)
            .then((data) => {
                if (data.status === "success") {
                    localStorage.setItem("current_user_id", data.user_id);
                    localStorage.setItem("current_username", data.username);
                    onAuthSuccess(data.user_id, data.username);
                }
                else {
                    throw new Error(data.detail || "注册失败")
                }
            })
        } catch (err) {
            setError(err.message);
        }
    };

    return (
        <div className="auth-card">
            <div className="auth-header">
                <h2>创建你的账户</h2>
                <p>提供身体解剖学指纹，以便我们为您拉起无污染的安全防线</p>
            </div>

            {error && <div className="auth-error-badge">⚠️ {error}</div>}

            <form onSubmit={handleSubmit} className="auth-form">
                <div className="form-row-grid">
                    <div className="form-group">
                        <label>用户昵称</label>
                        <input type="text" required placeholder="如: 张三" value={formData.username} onChange={e => setFormData({ ...formData, username: e.target.value })} />
                    </div>
                    <div className="form-group">
                        <label>安全密码</label>
                        <input type="password" required placeholder="请设置登录密码" value={formData.password} onChange={e => setFormData({ ...formData, password: e.target.value })} />
                    </div>
                </div>

                <div className="form-row-grid tri-grid">
                    <div className="form-group">
                        <label>生理性别</label>
                        <select value={formData.gender} onChange={e => setFormData({ ...formData, gender: e.target.value })}>
                            <option value="male">男 (Male)</option>
                            <option value="female">女 (Female)</option>
                            <option value="other">其他 (Other)</option>
                        </select>
                    </div>
                    <div className="form-group">
                        <label>身高 (cm)</label>
                        <input type="number" step="0.1" value={formData.height_cm} onChange={e => setFormData({ ...formData, height_cm: e.target.value })} />
                    </div>
                    <div className="form-group">
                        <label>体重 (kg)</label>
                        <input type="number" step="0.1" value={formData.weight_kg} onChange={e => setFormData({ ...formData, weight_kg: e.target.value })} />
                    </div>
                </div>

                <div className="form-row-grid">
                    <div className="form-group">
                        <label>体能水平</label>
                        <select value={formData.fitness_level} onChange={e => setFormData({ ...formData, fitness_level: e.target.value })}>
                            <option value="beginner">初学者 (Beginner)</option>
                            <option value="intermediate">进阶者 (Intermediate)</option>
                            <option value="advanced">高阶者 (Advanced)</option>
                        </select>
                    </div>
                    <div className="form-group">
                        <label>宏观训练目标</label>
                        <input type="text" placeholder="如：减脂、增肌、心肺强化" value={formData.fitness_goal} onChange={e => setFormData({ ...formData, fitness_goal: e.target.value })} />
                    </div>
                </div>

                <div className="form-group checkbox-section">
                    <label>🛠️ 家里或现有可用器械（多选）</label>
                    <div className="checkbox-flex">
                        {availableEquipments.map(eq => (
                            <label key={eq} className={`checkbox-tag ${formData.equipments.includes(eq) ? "active" : ""}`}>
                                <input type="checkbox" checked={formData.equipments.includes(eq)} onChange={() => handleCheckboxChange("equipments", eq)} />
                                {eq}
                            </label>
                        ))}
                    </div>
                </div>

                <div className="form-group checkbox-section">
                    <label>⚠️ 历史上受损或目前疼痛的关节（多选）</label>
                    <div className="checkbox-flex">
                        {injuryJoints.map(ij => (
                            <label key={ij} className={`checkbox-tag injury-tag ${formData.injuries.includes(ij) ? "active" : ""}`}>
                                <input type="checkbox" checked={formData.injuries.includes(ij)} onChange={() => handleCheckboxChange("injuries", ij)} />
                                {ij}
                            </label>
                        ))}
                    </div>
                </div>

                <button type="submit" className="auth-submit-btn">初始化长效语义记忆并进入系统</button>
            </form>
        </div>
    );
}
