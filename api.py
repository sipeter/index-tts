##Vibecoded eng ver that returns audio from http://127.0.0.1:8000/synthesize as binary blob
#https://github.com/index-tts/index-tts/pull/131
#orig auth https://github.com/itltf512116
from fastapi import FastAPI, UploadFile, File, Form, Body, Query
from fastapi.middleware.cors import CORSMiddleware # 导入
from fastapi.responses import FileResponse, JSONResponse, Response
import os
import time
import uvicorn
# --- 修改点 1: 导入 IndexTTS2 ---
from indextts.infer_v2 import IndexTTS2 
import tempfile
import hashlib
from typing import Dict
import base64
from pydantic import BaseModel

# 在文件顶部，确保导入这些模块
from fastapi.responses import StreamingResponse
import io
import uuid

app = FastAPI(title="IndexTTS API")


# --- 添加这部分 ---
# 允许所有来源。对于本地开发来说是安全的。
# 如果要部署到公网，可以指定具体的来源。
origins = ["*"] 

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"], # 允许所有 HTTP 方法
    allow_headers=["*"], # 允许所有 HTTP 头
)
# --- 添加结束 ---


# --- 修改点 2: 使用 IndexTTS2 初始化模型 ---
# Initialize the TTS model
# 修改说明：
# 1. 将 use_fp16 改为 is_fp16 (根据报错信息 TypeError: unexpected keyword argument 'use_fp16')
# 2. 删除 use_deepspeed (你当前的 infer_v2.py 版本不接受此参数，它会在内部根据 is_fp16 自动判断)
# 3. 如果你想开启降显存模式，请将 is_fp16 设为 True

tts = IndexTTS2(
    model_dir="checkpoints", 
    cfg_path="checkpoints/config.yaml",
    is_fp16=True,           # <--- 关键修改：改名为 is_fp16，设为 True 以启用半精度/低显存模式
    # use_deepspeed=False,  # <--- 关键修改：删除或注释掉这一行，因为该版本的 infer_v2 不支持在初始化时传入此参数
    use_cuda_kernel=False
)

# Ensure the 'prompts' and 'outputs' directories exist
os.makedirs("prompts", exist_ok=True)
os.makedirs("outputs", exist_ok=True) # Keep for other endpoints if needed

@app.post("/upload_audio")
async def upload_audio(audio: UploadFile = File(...)) -> Dict[str, str]:
    """
    Upload an audio file and save it
   
    Parameters:
    - audio: The audio file
   
    Returns:
    - A JSON response containing the saved filename
    """
    # Read the file content and calculate its MD5 hash
    content = await audio.read()
    md5_hash = hashlib.md5(content).hexdigest()
   
    # Get the file extension
    file_extension = os.path.splitext(audio.filename)[1]
    if not file_extension:
        file_extension = ".wav"  # Default extension
   
    # Generate a new filename
    new_filename = f"{md5_hash}{file_extension}"
    save_path = os.path.join("prompts", new_filename)
   
    # Save the file
    with open(save_path, "wb") as f:
        f.write(content)
   
    return {"filename": new_filename}

@app.post("/synthesize")
async def synthesize_speech(
    prompt_audio: UploadFile = File(...),
    text: str = Form(...),
    infer_mode: str = Form("普通推理")
):
    """
    Synthesize speech API
   
    Parameters:
    - prompt_audio: Reference audio file
    - text: Text to synthesize
    - infer_mode: Inference mode ("普通推理" or "批次推理")
   
    Returns:
    -  Audio file as a binary blob
    """
    # Create a temporary file to save the uploaded audio
    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_audio:
        content = await prompt_audio.read()
        temp_audio.write(content)
        temp_audio_path = temp_audio.name
   
    # Generate the output file path
    output_path = os.path.join("outputs", f"api_synth_{int(time.time())}.wav")
   
    try:
        # --- 修改点 3: 调整 infer 调用参数以适配 V2 ---
        # V2 版本 infer 方法参数名有所变化，这里显式指定参数名以防万一
        if infer_mode == "普通推理":
            output = tts.infer(spk_audio_prompt=temp_audio_path, text=text, output_path=output_path)
        else:
            # 如果 IndexTTS2 没有 infer_fast，回退到普通 infer，或者根据库的实际情况调用
            # 这里的调用方式假设 infer_fast 签名未变，或者暂时使用 infer 代替
            # output = tts.infer_fast(temp_audio_path, text, output_path) 
            # 保险起见，V2 API 建议统一使用 infer
            output = tts.infer(spk_audio_prompt=temp_audio_path, text=text, output_path=output_path)
       
        # Read the generated audio file
        with open(output, "rb") as audio_file:
            audio_data = audio_file.read()
       
        # Return the audio data as a binary blob with appropriate content type
        return Response(content=audio_data, media_type="audio/wav")
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={
                "code": 1,
                "message": f"Synthesis failed: {str(e)}"
            }
        )
    finally:
        # Clean up the temporary file
        os.unlink(temp_audio_path)
        # Also clean up the output file if it exists
        if os.path.exists(output_path):
            try:
                os.unlink(output_path)
            except:
                pass


class SynthesizeRequest(BaseModel):
    filename: str
    text: str
    infer_mode: str = "普通推理"

@app.post("/synthesize_by_filename")
async def synthesize_speech_by_filename(request: SynthesizeRequest = Body(...)):
    """
    Synthesize speech using an uploaded audio file
   
    Parameters:
    - request: Request body containing filename, text, and infer_mode
   
    Returns:
    - Audio file as binary blob
    """
    # Construct the full path to the audio file
    prompt_audio_path = os.path.join("prompts", request.filename)
   
    # Check if the file exists
    if not os.path.exists(prompt_audio_path):
        return JSONResponse(
            status_code=404,
            content={
                "code": 2,
                "message": f"Audio file {request.filename} does not exist"
            }
        )
   
    # Generate the output file path
    output_path = os.path.join("outputs", f"api_synth_{int(time.time())}.wav")
   
    try:
        # --- 修改点 4: 调整 infer 调用参数以适配 V2 ---
        if request.infer_mode == "普通推理":
            output = tts.infer(spk_audio_prompt=prompt_audio_path, text=request.text, output_path=output_path)
        else:
            # 同上，保险起见统一使用 infer
            output = tts.infer(spk_audio_prompt=prompt_audio_path, text=request.text, output_path=output_path)
       
        # Read the generated audio file
        with open(output, "rb") as audio_file:
            audio_data = audio_file.read()
       
        # Return the audio data as a binary blob
        return Response(content=audio_data, media_type="audio/wav")
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "code": 1,
                "message": f"Synthesis failed: {str(e)}"
            }
        )
    finally:
        # Clean up the generated file
        if os.path.exists(output_path):
            try:
                os.unlink(output_path)
            except:
                pass

# ======================================================================================
# START: 新增的 GET 端点 (最终修复版)
# ======================================================================================
@app.get("/synthesize_get")
async def synthesize_speech_get(
    filename: str = Query(..., description="位于 'prompts' 文件夹中的参考音频文件名"),
    text: str = Query(..., description="需要合成的文本"),
    infer_mode: str = Query("普通推理", description="推理模式: '普通推理' 或 '批次推理'")
):
    """
    通过GET请求，使用服务器上已有的音频文件合成语音，并直接返回音频流。
    此方法不会在服务器上保存生成的音频文件。
    """
    # 1. 构造参考音频的完整路径
    prompt_audio_path = os.path.join("prompts", filename)

    # 2. 检查参考音频文件是否存在
    if not os.path.exists(prompt_audio_path):
        return JSONResponse(
            status_code=404,
            content={
                "code": 2,
                "message": f"参考音频文件 '{filename}' 不存在于 'prompts' 文件夹中"
            }
        )

    # 【关键修复】模仿POST方法的成功逻辑：
    # 创建一个手动的、唯一的临时输出路径，而不是使用with语句块管理文件对象。
    # 这确保了写入和读取操作是分离的。
    temp_output_path = os.path.join(tempfile.gettempdir(), f"{uuid.uuid4()}.wav")
    
    try:
        # 3. 调用 TTS 模型进行合成，让它完整地写入文件并关闭
        # --- 修改点 5: 调整 infer 调用参数以适配 V2 ---
        tts.infer(spk_audio_prompt=prompt_audio_path, text=text, output_path=temp_output_path)

        # 4. 检查文件是否真的生成了并且有内容
        if not os.path.exists(temp_output_path) or os.path.getsize(temp_output_path) == 0:
            raise RuntimeError("TTS failed to generate a valid audio file.")

        # 5. 现在，独立地打开并读取这个已完整写入的文件
        with open(temp_output_path, "rb") as audio_file:
            audio_data = audio_file.read()

        # 6. 将音频数据放入内存流并使用StreamingResponse返回
        #    这是最健壮的返回流数据的方式。
        audio_stream = io.BytesIO(audio_data)
        return StreamingResponse(audio_stream, media_type="audio/wav")

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={
                "code": 1,
                "message": f"语音合成失败: {str(e)}"
            }
        )
    finally:
        # 7. 【关键】无论成功还是失败，都确保删除临时文件
        if os.path.exists(temp_output_path):
            try:
                os.unlink(temp_output_path)
            except:
                pass
# ======================================================================================
# END: 新增的 GET 端点
# ======================================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)