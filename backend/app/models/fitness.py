from pydantic import BaseModel, Field
from typing import List, Optional, Literal, Dict, Any
from datetime import datetime
from app.models.schema import FullPlan, ToolCallIntent, ExerciseBase
from app.models.memory import ChatMessage

class ChatSession(BaseModel):
    """会话主表持久化模型"""
    session_id: str
    user_id: int
    created_at: Optional[datetime] = Field(None, description="会话建立时间")
    updated_at: Optional[datetime] = Field(None, description="会话更新时间")
    
    # 级联包含当前会话下的全量原始聊天记录，供前端随时上滑无感拉取历史对账
    records: List[ChatMessage] = Field(default_factory=list, description="本会话内未经滑窗裁剪的原始问答")


class ChatRecord(BaseModel):
    """
    2. 聊天明细流水账表 (chat_records)
    职责：全量保留每一轮多轮问答原文字符串，供前端上滑无感拉取历史聊天记录
    """
    id: Optional[int] = Field(None)
    session_id: str
    role: Literal["user", "assistant"] = Field(..., description="对话角色标签")
    content: str = Field(..., description="agent返回回答的JSON镜像")
    created_at: Optional[datetime] = Field(None, description="本条对话的时间戳")


class AgentPlansLog(BaseModel):
    """
    3. 编排大脑决策与质检审计日志表 (agent_plans_log)
    职责：高密度固化大、小 Planner 参数、自愈循环重试次数以及生数据快照，建立大厂级硬核线上排障与审计线
    """
    id: Optional[int]
    session_id: str
    user_query: str
    loop_retry_count: int = Field(0, description="本轮大循环中，系统由于被 Analyzer 拦截打回了多少次")
    
    macro_blueprint: List[ToolCallIntent] = Field(..., description="大planner产出的宏观多实例工具选装拓扑蓝图快照镜像数组")
    native_full_plan: FullPlan = Field(..., description="小planner并发拼装、对齐了专属子原因和focused_query后的完全体 FullPlan")
    executed_results: str = Field(..., description="ToolExecutor的原始执行结算快照报告数组")
    
    analyzer_final_reason: Optional[str] = Field(None, description="analyzer最后一轮的深度诊断分析")
    created_at: Optional[datetime] = Field(None, description="审计日志物理落盘固化的时间戳")


class TrainingLog(BaseModel):
    """
    4. 固化的训练课表记录表 (training_logs)
    职责：彻底固化 Synthesizer 喷射出的 CoachResponse.exercises 满血卡片资产，供用户前端每天真实打卡与历史课表回溯
    """
    log_id: Optional[int] = Field(None, description="log id")
    user_id: int
    session_id: str
    coach_reply_summary: Optional[str] = Field(None, description="本次课表的简介大纲")
    generated_plan_json: List[ExerciseBase] = Field(..., description="生成的完整结构化动作卡片对象数组")
    
    is_completed: int = Field(0, description="训练打卡标记。0:大模型生成未练, 1:用户打卡完成")
    created_at: Optional[datetime] = Field(None, description="训练计划生成的时间戳")
