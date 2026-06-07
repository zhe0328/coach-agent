from pydantic import BaseModel, Field
from typing import List, Literal, Optional

class ChatMessage(BaseModel):
    """单条对话契约"""
    role: str  # "user" 或 "assistant"
    content: str

class WorkingMemory(BaseModel):
    """当前会话的工作记忆完全体模型（绑定 Session 生命周期）"""
    session_id: str
    chat_history: List[ChatMessage] = Field(default_factory=list, description="近期滑窗内的标准对话历史")
    
    # 💡 核心高级特性：状态机自愈状态留存
    current_loop_retry_count: int = Field(0, description="记录当前轮次中，Planner 已经因质检失败重试了多少次")
    latest_analyzer_feedback: str = Field("", description="留存 Analyzer 在上一轮自愈迭代中吐出的具体反思指令")
    
    def add_message(self, role: str, content: str):
        self.chat_history.append(ChatMessage(role=role, content=content))
        
    def reset_loop_state(self):
        """当 Synthesizer 最终成功喷射完文本、一轮完整对话彻底闭环时，重置重试计数器"""
        self.current_loop_retry_count = 0
        self.latest_analyzer_feedback = ""

# 💡 锁死大模型裁判被允许提取的解剖学关节名称（必须与你 Neo4j 里的 Joint 节点 Name 绝对一致）
JOINT_LITERAL = Literal["脊柱", "肩关节", "膝关节", "踝关节", "腕关节", "肘关节", "髋关节"]

class InjurySnifferSchema(BaseModel):
    """
    后台长效语义记忆巩固器专用的【伤病与痛点嗅探模型】
    """
    has_new_injury: bool = Field(
        ..., 
        description="用户在此轮对话中是否明确、主观表达了身体某处关节疼痛、酸痛、受伤、弹响、卡顿或活动受限。若只是普通的训练交流则为 false。"
    )
    
    joint: Optional[List[JOINT_LITERAL]] = Field(
        None, 
        description="受损或不适的身体关节名称。必须严格从允许的解剖学关节列表中选择。若 has_new_injury 为 false，则此处必须保持 null (None)。"
    )
    
    severity: Literal["temporary_pain", "chronic_injury", "none"] = Field(
        "none",
        description="伤病严重度初步评估。口语化酸痛/不适选 temporary_pain；明确提到确诊伤病（如腰椎间盘突出、肩袖撕裂）选 chronic_injury；无伤病选 none。"
    )
    
    reason: str = Field(
        ..., 
        description="简短摘录或分析用户对话中透露出伤病的客观依据（如：用户主诉深蹲时膝盖有弹响）。"
    )

    has_new_equipment: bool = Field(
        ..., description="用户是否提到了自己【新买了解锁、或者可以用】的新器材。"
    )
    equipment_name: Optional[List[str]] = Field(None)

    has_injury_resolution: bool = Field(
        False,
        description="用户明确表示档案中的伤病/不适已恢复、痊愈或不再构成训练限制。",
    )
    resolved_joints: Optional[List[JOINT_LITERAL]] = Field(
        None,
        description="已从不适中恢复的关节。仅当 has_injury_resolution 为 true 时填写。",
    )

    has_equipment_removal: bool = Field(
        False,
        description="用户明确表示不再拥有、无法使用或不再使用某些器材。",
    )
    removed_equipment: Optional[List[str]] = Field(None)

    conflicts_with_stored_profile: bool = Field(
        False,
        description="本轮原话是否与已存储的伤病/器械画像存在明显矛盾。",
    )
    conflict_resolution: Literal["trust_current_input", "keep_stored_profile", "none"] = Field(
        "none",
        description="出现矛盾时的裁决：优先采信本轮原话 / 保留档案 / 无矛盾。",
    )
    conflict_reason: str = Field(
        "",
        description="若存在矛盾，简述矛盾点与裁决依据。",
    )
    