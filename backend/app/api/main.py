from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from ..tools.sql_tool import SQLTool
from ..config import get_settings
from ..agent.orchestrator import CoachOrchestrator
from ..models.schema import (
    ChatRequest,
    ExerciseDetail,
    UserProfileRequest,
    UserSignupRequest,
    AuthResponse,
    UserLoginRequest,
)
from ..agent.utils.logger import logger, LogColor
from ..queue.enqueue import enqueue_user_semantic_init
from ..serving.session_lock import SessionLockNotAcquired, is_session_locked
from .auth import (
    TokenPayload,
    assert_user_matches_token,
    create_access_token,
    get_current_user,
)
from openai import OpenAI
import json
import os
import bcrypt

settings = get_settings()

client = OpenAI(
    api_key=settings.OPENAI_API_KEY,
    base_url=settings.OPENAI_BASE_URL,
)
orchestrator = CoachOrchestrator(client)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if settings.STARTUP_WARMUP_ENABLED:
        try:
            from ..agent.cache.warmup import warmup_intent_resources

            await warmup_intent_resources(
                orchestrator.sql_tool,
                orchestrator.graph_tool,
            )
        except Exception as exc:
            logger.warning(f"{LogColor.PLAN}[Warmup] skipped: {exc}{LogColor.RESET}")
    yield


app = FastAPI(lifespan=lifespan)

sql_tool = SQLTool()

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_cors_origins_list(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

current_dir = os.path.dirname(os.path.abspath(__file__))
static_dir = os.path.join(current_dir, "../../../static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/v1/exercises/{exercise_id}", response_model=ExerciseDetail)
async def get_exercise(exercise_id: str):
    """获取特定动作详情"""
    try:
        result = await sql_tool.search_exercise_detail(exercise_id)
        if not result:
            raise HTTPException(
                status_code=404, detail=f"Exercise with id {exercise_id} not found"
            )
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"API Error fetching exercise {exercise_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


def _session_busy_http_exception(exc: SessionLockNotAcquired) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail="Session is processing another message. Please retry shortly.",
        headers={"Retry-After": str(exc.retry_after)},
    )


@app.post("/v1/chat")
async def chat_endpoint(
    request: ChatRequest,
    current_user: TokenPayload = Depends(get_current_user),
):
    """SSE streaming chat — runs pipeline through analyzer, streams synthesizer output."""
    assert_user_matches_token(request.user_id, current_user)

    if await is_session_locked(request.session_id):
        raise _session_busy_http_exception(
            SessionLockNotAcquired(
                request.session_id,
                retry_after=settings.SESSION_LOCK_RETRY_AFTER_SECONDS,
            )
        )

    async def generate():
        try:
            async for event in orchestrator.execute_stream(
                request.user_id,
                request.session_id,
                request.message,
            ):
                yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
        except SessionLockNotAcquired as exc:
            error_event = {
                "type": "error",
                "code": 409,
                "detail": str(exc),
                "retry_after": exc.retry_after,
            }
            yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.post("/v1/chat/static")
async def chat_static(
    request: ChatRequest,
    current_user: TokenPayload = Depends(get_current_user),
):
    assert_user_matches_token(request.user_id, current_user)
    try:
        response = await orchestrator.execute(
            request.user_id, request.session_id, request.message
        )
    except SessionLockNotAcquired as exc:
        raise _session_busy_http_exception(exc) from exc
    if hasattr(response, "model_dump"):
        return {"data": response.model_dump()}
    return {"data": response}


@app.post("/v1/user/signup", response_model=AuthResponse)
async def sign_up_user(request: UserSignupRequest):
    try:
        logger.info(
            f"{LogColor.TOOL}[AuthAPI] 👤 接收到新用户注册与身体问卷初始化请求，用户名: '{request.username}'{LogColor.RESET}"
        )
        new_user_id = await sql_tool.init_user(request)

        injuries_list = (
            [i.strip() for i in request.injuries.split(",") if i.strip()]
            if request.injuries
            else []
        )
        equipments_list = (
            [e.strip() for e in request.equipments.split(",") if e.strip()]
            if request.equipments
            else ["自重"]
        )

        enqueue_user_semantic_init(
            user_id=new_user_id,
            name=request.username,
            level=request.fitness_level,
            injuries=injuries_list,
            equipments=equipments_list,
        )

        token = create_access_token(new_user_id, request.username)
        return AuthResponse(
            user_id=new_user_id,
            username=request.username,
            access_token=token,
            status="success",
        )
    except Exception as e:
        logger.error(f"[AuthAPI] 注册事务全盘崩溃打回: {e}")
        raise HTTPException(
            status_code=400, detail=f"注册失败或用户名已被占用: {str(e)}"
        )


@app.post("/v1/user/login", response_model=AuthResponse)
async def login(request: UserLoginRequest):
    logger.info(
        f"[AuthAPI] 🔑 收到用户登录请求，尝试验证账户: '{request.username}'"
    )
    user_data: dict = await sql_tool.get_user_credentials_by_name(request.username)

    if not user_data:
        raise HTTPException(status_code=401, detail="账户不存在或密码验证失败")

    db_password_hash = user_data.get("password_hash")
    db_user_id = user_data.get("user_id")

    is_password_valid = bcrypt.checkpw(
        request.password.encode("utf-8"),
        db_password_hash.encode("utf-8"),
    )

    if not is_password_valid:
        logger.warning(f"[AuthAPI] ❌ 账户 '{request.username}' 密码验证失败！")
        raise HTTPException(status_code=401, detail="账户不存在或密码验证失败")

    logger.info(
        f"✅ [AuthAPI] 账户 '{request.username}' (ID: {db_user_id}) 鉴权通过。"
    )
    token = create_access_token(db_user_id, request.username)
    return AuthResponse(
        user_id=db_user_id,
        username=request.username,
        access_token=token,
        status="success",
    )


@app.post("/v1/user/profile/update")
async def update_profile(
    request: UserProfileRequest,
    current_user: TokenPayload = Depends(get_current_user),
):
    if request.user_id is not None:
        assert_user_matches_token(request.user_id, current_user)

    logger.info(
        f"{LogColor.TOOL}[AuthAPI] ⚙️ 收到用户 ID: {request.user_id} 的语义记忆动态演进更新请求{LogColor.RESET}"
    )

    try:
        await sql_tool.update_user_profile(request)

        injuries_list = (
            [i.strip() for i in request.injuries.split(",") if i.strip()]
            if request.injuries
            else []
        )
        equipments_list = (
            [e.strip() for e in request.equipments.split(",") if e.strip()]
            if request.equipments
            else ["自重"]
        )

        enqueue_user_semantic_init(
            user_id=request.user_id,
            name=request.username,
            level=request.fitness_level,
            injuries=injuries_list,
            equipments=equipments_list,
        )

        return {"status": "success", "message": "长效语义画像与生理防线升级完毕"}

    except Exception as e:
        logger.error(f"[AuthAPI] 画像动态演进发生崩溃: {e}")
        raise HTTPException(status_code=500, detail=f"长效记忆更新失败: {str(e)}")


@app.get("/v1/user/profile/{id}", response_model=UserProfileRequest)
async def get_profile(
    id: int, current_user: TokenPayload = Depends(get_current_user)
):
    assert_user_matches_token(id, current_user)
    try:
        result = await sql_tool.search_profile(id)
        if not result:
            raise HTTPException(status_code=404, detail=f"User with id {id} not found")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"API Error fetching user {id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/chat/sessions/{user_id}")
async def get_user_sessions(
    user_id: str, current_user: TokenPayload = Depends(get_current_user)
):
    assert_user_matches_token(int(user_id), current_user)
    try:
        result = await sql_tool.get_user_sessions(user_id)
        if not result:
            raise HTTPException(
                status_code=404, detail=f"No sessions for user {user_id}"
            )
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"API Error fetching user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/v1/chat/sessions/{session_id}/close")
async def close_chat_session(
    session_id: str,
    current_user: TokenPayload = Depends(get_current_user),
):
    try:
        owner_id = await sql_tool.get_session_user_id(session_id)
        if owner_id is None:
            raise HTTPException(
                status_code=404, detail=f"Session {session_id} not found"
            )
        assert_user_matches_token(owner_id, current_user)

        return await orchestrator.close_session(owner_id, session_id)
    except SessionLockNotAcquired as exc:
        raise _session_busy_http_exception(exc) from exc
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"API Error closing session {session_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/chat/history/{session_id}")
async def get_session_details(
    session_id: str, current_user: TokenPayload = Depends(get_current_user)
):
    try:
        owner_id = await sql_tool.get_session_user_id(session_id)
        if owner_id is None:
            raise HTTPException(
                status_code=404, detail=f"Session {session_id} not found"
            )
        assert_user_matches_token(owner_id, current_user)

        result = await sql_tool.get_session_details(session_id)
        if not result:
            raise HTTPException(
                status_code=404, detail=f"Session {session_id} not found"
            )
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"API Error fetching session {session_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

    try:
        result = await sql_tool.get_session_details(session_id)
        if not result:
            raise HTTPException(
                status_code=404, detail=f"User with id {id} not found"
            )

        return result
    except Exception as e:
        print(f"API Error fetching session {session_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")