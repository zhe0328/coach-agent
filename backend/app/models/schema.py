from decimal import Decimal
from pydantic import BaseModel, Field
from typing import List, Optional, Literal

class UserProfileRequest(BaseModel): 
    user_id: Optional[int] = Field(None, description="user id")
    username: str
    gender: Literal["male", "female", "other"]
    weight_kg: float
    height_cm: float
    fitness_level: Literal["beginner", "intermediate", "advanced"]
    fitness_goal: str
    equipments: str
    injuries: str


class UserSignupRequest(UserProfileRequest):
    password: str

class UserLoginRequest(BaseModel):
    username: str
    password: str

class AuthResponse(BaseModel):
    user_id: int
    username: str
    access_token: str = Field(..., description="JWT bearer token for protected APIs")
    token_type: str = Field("bearer", description="Token type for Authorization header")
    status: str = Field("success", description="鉴权状态标记")

class ChatRequest(BaseModel):
    session_id: str = Field(..., description="前端生成的唯一会话UUID，用于锁定工作记忆空间")
    user_id: int
    message: str


class RAGSearchSchema(BaseModel):
    query_text: str = Field(
        ..., description="用户的健身问题，例如'如何缓解久坐腰痛'、'波比跳怎么做'"
    )
    top_k: int = Field(5, description="检索相关的知识条目数量")
    intent: Literal["exercise", "knowledge", "mixed"] = Field(
        ..., 
        description="exercise: 仅查询特定动作实操/发力感; knowledge: 查询动作组合逻辑/生理机制/课表编排/疲劳等理论; mixed: 两者皆有"
    )

class GraphReasoningSchema(BaseModel):
    exercise_name: Optional[str] = Field(None, description="动作名称")
    muscle_name: Optional[str] = Field(None, description="肌肉名称，如'胸肌'")
    joint_name: Optional[Literal["脊柱", "肩关节", "膝关节", "踝关节", "腕关节", "肘关节", "髋关节"]] = Field(None, description="受损关节名称，如'膝关节'")
    scenario: Literal[
        "injury_avoidance", "progression", "regression", "synergy", "strengthen_joint"
    ]
    candidate_ids: Optional[List[str]] = Field(
        default=None, 
        description="系统并行拦截引擎动态注入的候选动作 ID 列表，大模型在 Planner 阶段【无需手动填充】"
    )


class ExerciseFields(BaseModel):
    name_zh: Optional[str] = Field(None, description="动作名称")
    body_part_zh: Optional[Literal["背部", "心脏", "胸部", "前臂", "小腿", "颈部", "肩部", "上臂", "大腿", "腰腹"]] = Field(None, description="身体部位")
    equipment_zh: Optional[str] = Field(None, description="器材名称")
    target_zh: Optional[str] = Field(None, description="目标肌肉")
    difficulty: Optional[Literal["beginner", "intermediate", "advanced"]] = Field(None, description="难度等级")
    category_zh: Optional[Literal["力量训练", "有氧运动", "平衡训练", "灵活性训练", "爆发力训练", "康复训练", "拉伸放松"]] = Field(None, description="运动分类")


class SQLSearchSchema(ExerciseFields):
    equipment_zh: Optional[str | List[str]] = Field(
        None, description="器材名称，支持单个或多个"
    )
    limit: int = Field(default=4, description="返回动作的数量限制")


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
    data_type: Literal["exercise"] = "exercise"

class ToolCallIntent(BaseModel):
    task_id: str = Field(..., description="如 task_sql_base, task_graph_injury, task_rag_query")
    tool_name: Literal["sql_tool", "graph_tool", "rag_tool"]
    rag_intent: Optional[Literal["exercise", "knowledge", "mixed"]] = Field(None, description="仅当 tool_name 为 rag_tool 时必填")
    depends_on: Optional[List[str]] = Field(
        default=[], 
        description="本任务依赖的其他 task_id 列表。只有当这些任务执行完，本任务才能启动并读取它们的数据。"
    )
    reason: str = Field(default="", description="选择该工具的原因")
    focused_query: str = Field(..., description="针对该工具剥离噪音后的定向用户提问切片（如：'用哑铃练胸'）")
    limit: int = Field(default=4, description="返回动作的数量限制")

class MacroPlanSchema(BaseModel):
    routing_mode: Literal["standard", "chat_only"] = Field(
        "standard", 
        description="standard: 需要调用工具库; chat_only: 纯寒暄、日常问候或无法触发任何工具的闲聊"
    )
    selected_tools: List[ToolCallIntent] = Field(..., description="选装的工具链拓扑图")
    routing_reason: str = Field(..., description="做出该工具组合选择的简短依据")


class ToolTask(BaseModel):
    task_id: str
    tool: Literal["sql_tool", "graph_tool", "rag_tool"]
    sql_params: Optional[SQLSearchSchema] = None
    rag_params: Optional[RAGSearchSchema] = None
    graph_params: Optional[GraphReasoningSchema] = None
    reason: str = Field(default="", description="选择该工具的原因")
    depends_on: Optional[List[str]] = Field(
        default=[], 
        description="本任务依赖的其他 task_id 列表。只有当这些任务执行完，本任务才能启动并读取它们的数据。"
    )

class KnowledgeChunk(BaseModel):
    """高密度生理学、组合原理与文献理论模型"""
    id: str
    source_book: str = Field(..., description="图书或文献来源文件名")
    chapter_title: str = Field(..., description="所属章节或宏观主题")
    category: str = Field("physiology_and_logic", description="知识分类")
    core_principles: List[str] = Field(default_factory=list, description="该切片命中的核心生理学/组合机制标签")
    content: str = Field(..., description="未经魔改的教科书高密度原文文本")
    cosine_similarity: float = Field(..., description="向量匹配的绝对余弦相似度")
    data_type: Literal["knowledge"] = "knowledge"  # 👈 显式类型判别器

class FullPlan(BaseModel):
    tasks: List[ToolTask]
    logic_chain: str = Field(..., description="总体的推理思路")


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
    references: List[str] = Field(
        default_factory=list, 
        description="本次执教方案所高保真引用的全部底层 MySQL/Chroma/Neo4j 原始文献与客观规律快照数组"
    )
    selected_tools: List[Literal["sql_tool", "graph_tool", "rag_tool"]]
