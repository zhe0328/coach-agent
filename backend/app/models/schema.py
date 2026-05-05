from pydantic import BaseModel, Field
from typing import List, Optional, Dict
from enum import Enum

class DifficultyLevel(str, Enum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"

class ExerciseBase(BaseModel):
    """单体动作的基础数据结构"""
    id: str
    name_zh: str
    difficulty: DifficultyLevel
    body_part_zh: str
    equipment_zh: str
    target_zh: str
    category_zh: str
    
class ExerciseDetail(ExerciseBase):
    """包含完整指导说明的动作详情"""
    instructions_zh: List[str] = []
    secondary_muscles_zh: List[str] = []
    description_zh: Optional[str] = None
    gif_path: Optional[str] = None

class TrainingLogic(BaseModel):
    """动作的教练逻辑扩展（为 SKILL.md 准备）"""
    progression_ids: List[str] = []  # 进阶动作 ID 列表
    regression_ids: List[str] = []   # 退让动作 ID 列表
    contraindications: List[str] = [] # 禁忌症 (如：腰痛禁做)
    
class CoachRecommendation(BaseModel):
    """Agent 最终输出的推荐结构"""
    user_intent: Dict
    planned_exercises: List[ExerciseDetail]
    warmup_tips: str
    safety_notes: str
