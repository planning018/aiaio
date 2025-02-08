import asyncio
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from aiaio import __version__, logger
from aiaio.db import ChatDatabase


logger.info("aiaio...")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = FastAPI()
static_path = os.path.join(BASE_DIR, "static")
app.mount("/static", StaticFiles(directory=static_path), name="static")
templates_path = os.path.join(BASE_DIR, "templates")
templates = Jinja2Templates(directory=templates_path)

# Create temp directory for uploads
TEMP_DIR = Path(tempfile.gettempdir()) / "aiaio_uploads"
TEMP_DIR.mkdir(exist_ok=True)

# Initialize database
db = ChatDatabase()

CONV_HISTORY = []


class FileAttachment(BaseModel):
    name: str
    type: str
    data: str


class MessageContent(BaseModel):
    text: str
    files: Optional[List[FileAttachment]] = None


class ChatInput(BaseModel):
    message: str
    system_prompt: str
    conversation_id: Optional[str] = None


class MessageInput(BaseModel):
    role: str
    content: str
    content_type: str = "text"
    attachments: Optional[List[Dict]] = None


class SettingsInput(BaseModel):
    temperature: Optional[float] = 1.0
    max_tokens: Optional[int] = 4096
    top_p: Optional[float] = 0.95
    host: Optional[str] = "http://localhost:8000"
    model_name: Optional[str] = "meta-llama/Llama-3.2-1B-Instruct"
    api_key: Optional[str] = "YOUR_API_KEY"


async def fake_text_streamer():
    for i in range(5):
        yield f"Hello {i}\n"
        await asyncio.sleep(1)


@app.get("/", response_class=HTMLResponse)
async def load_index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/version")
async def version():
    return {"version": __version__}


@app.get("/conversations")
async def get_conversations():
    try:
        conversations = db.get_all_conversations()
        return {"conversations": conversations}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str):
    try:
        history = db.get_conversation_history(conversation_id)
        if not history:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return {"messages": history}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/create_conversation")
async def create_conversation():
    try:
        conversation_id = db.create_conversation()
        return {"conversation_id": conversation_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/conversations/{conversation_id}/messages")
async def add_message(conversation_id: str, message: MessageInput):
    try:
        message_id = db.add_message(
            conversation_id=conversation_id,
            role=message.role,
            content=message.content,
            content_type=message.content_type,
            attachments=message.attachments,
        )
        return {"message_id": message_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str):
    try:
        db.delete_conversation(conversation_id)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    

@app.post("/save_settings")
async def save_settings(settings: SettingsInput):
    try:
        # Save settings to database
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/chat", response_class=StreamingResponse)
async def chat(
    message: str = Form(...),
    system_prompt: str = Form(...),
    conversation_id: str = Form(...),  # Now required
    file: Optional[UploadFile] = File(None),
):
    try:
        logger.info(f"Chat request: message='{message}' conv_id={conversation_id} system_prompt='{system_prompt}'")

        # Verify conversation exists
        # history = db.get_conversation_history(conversation_id)
        # if not history:
        #     raise HTTPException(status_code=404, detail="Conversation not found")

        # Handle file upload
        file_info = None
        if file:
            # Get file size by reading the file into memory first
            contents = await file.read()
            file_size = len(contents)

            # Create unique filename
            temp_file = TEMP_DIR / f"{file.filename}"
            try:
                # Save uploaded file
                with open(temp_file, "wb") as f:
                    f.write(contents)
                file_info = {
                    "name": file.filename,
                    "path": str(temp_file),
                    "type": file.content_type,
                    "size": file_size,
                }
                logger.info(f"Saved uploaded file: {temp_file} ({file_size} bytes)")
            except Exception as e:
                logger.error(f"Failed to save uploaded file: {e}")
                raise HTTPException(status_code=500, detail=f"Failed to process uploaded file: {str(e)}")

        # Store messages in database
        db.add_message(conversation_id=conversation_id, role="system", content=system_prompt)

        db.add_message(
            conversation_id=conversation_id,
            role="user",
            content=message,
            attachments=[file_info] if file_info else None,
        )

        complete_response = []

        async def process_and_stream():
            if file_info:
                acknowledgment = f"I received your message and the file '{file_info['name']}'.\n"
                complete_response.append(acknowledgment)
                yield acknowledgment

            async for chunk in fake_text_streamer():
                complete_response.append(chunk)
                yield chunk

            db.add_message(conversation_id=conversation_id, role="assistant", content="".join(complete_response))

            # Cleanup temp file
            if file_info:
                try:
                    os.remove(file_info["path"])
                except Exception as e:
                    logger.error(f"Failed to remove temp file: {e}")

        return StreamingResponse(process_and_stream())

    except Exception as e:
        logger.error(f"Error in chat endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
