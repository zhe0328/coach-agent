from pydantic import BaseModel, Field
from typing import List, Optional, Literal

class ChatRequest(BaseModel):
    user_id: int
    message: str


class RAGSearchSchema(BaseModel):
    query_text: str = Field(
        ..., description="用户的健身问题，例如'如何缓解久坐腰痛'、'波比跳怎么做'"
    )
    top_k: int = Field(3, description="检索相关的知识条目数量")


class GraphReasoningSchema(BaseModel):
    exercise_name: Optional[str] = Field(None, description="动作名称")
    muscle_name: Optional[str] = Field(None, description="肌肉名称，如'胸肌'")
    joint_name: Optional[str] = Field(None, description="受损关节名称，如'膝关节'")
    scenario: Literal[
        "injury_avoidance", "progression", "regression", "synergy", "strengthen_joint"
    ]


class ExerciseFields(BaseModel):
    name_zh: Optional[str] = Field(None, description="动作名称")
    body_part_zh: Optional[Literal["背部", "心脏", "胸部", "前臂", "小腿", "颈部", "肩部", "上臂", "大腿", "腰腹"]] = Field(None, description="身体部位")
    equipment_zh: Optional[str] = Field(None, description="器材名称")
    target_zh: Optional[str] = Field(None, description="目标肌肉")
    difficulty: Optional[Literal["beginner", "intermediate", "advanced"]] = Field(None, description="难度等级")
    category_zh: Optional[Literal["力量训练", "有氧运动", "平衡训练", "灵活性训练", "爆发力训练", "康复训练", "拉伸放松"]] = Field(None, description="运动分类")


class SQLSearchSchema(ExerciseFields):
    limit: int = Field(3, description="返回动作的数量限制")


class ExerciseBase(ExerciseFields):
    """单体动作的基础数据结构"""

    id: str


class ExerciseDetail(ExerciseBase):
    """包含完整指导说明的动作详情"""

    instructions_zh: List[str] = []
    secondary_muscles_zh: List[str] = []
    description_zh: Optional[str] = None
    gif_path: Optional[str] = None
    rag_content: Optional[str] = None


class ToolTask(BaseModel):
    tool: Literal["sql_tool", "graph_tool", "rag_tool"]
    sql_params: Optional[SQLSearchSchema] = None
    rag_params: Optional[RAGSearchSchema] = None
    graph_params: Optional[GraphReasoningSchema] = None
    reason: str = Field(..., description="选择该工具的原因")


class IntentPlan(BaseModel):
    """Planner 输出的执行蓝图"""

    tasks: List[ToolTask]
    rag_keywords: Optional[str] = Field(
        None, description="如果涉及 RAG，压缩后的关键词"
    )
    logic_chain: str = Field(..., description="Agent 的思考链条 (CoT)")


class FullPlan(BaseModel):
    tasks: List[ToolTask]
    logic_chain: str = Field(..., description="总体的推理思路")


class TrainingLogic(BaseModel):
    """动作的教练逻辑扩展（为 SKILL.md 准备）"""

    progression_ids: List[str] = []  # 进阶动作 ID 列表
    regression_ids: List[str] = []  # 退让动作 ID 列表
    contraindications: List[str] = []  # 禁忌症 (如：腰痛禁做)

class CoachResponse(BaseModel):
    """
    高度复用的前端展示模型
    JD 亮点：支持多模态任务结果合并，适配宽泛咨询与精准推荐
    """
    # 响应类型：用于前端决定 UI 布局
    response_type: Literal["recommendation", "knowledge", "safety_warning", "nutrition"] = Field(
        ..., description="响应类型，决定前端是展示卡片流还是长文章"
    )
    
    greeting: str = Field(..., description="开场白")
    
    # 场景 A：精准动作推荐 (SQL/GraphRAG 产出)
    exercises: Optional[List[ExerciseBase]] = Field(
        None, description="动作卡片列表，若是纯知识回答则为 None"
    )
    
    # 场景 B：宽泛知识讲解 (RAG/LLM 产出)
    # 用于回答：发力感细节、HIIT建议、饮食结合等
    detailed_guidance: Optional[str] = Field(
        None, description="深度指导文本，支持 Markdown 格式"
    )
    
    safety_alerts: List[str] = Field(default=[], description="安全警告")
    summary: str = Field(..., description="总结建议")
    medical_disclaimer: str = Field("以上建议仅供参考，如需获取医疗建议或诊断信息，请咨询专业人士。", description="免责声明")
