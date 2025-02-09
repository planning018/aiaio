import asyncio
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from openai import OpenAI
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
    api_key: Optional[str] = ""


async def text_streamer(messages: List[Dict[str, str]]):
    """
    Generate text stream from LLM
    example messages:
    [{'message_id': 'c4d7ffae-9b08-4428-a8c7-7e58db061d54', 'conversation_id': 'ded63e06-b42b-47ca-9627-59df796fdd06', 'role': 'system', 'content_type': 'text', 'content': 'pikachoo', 'created_at': 1739082937.895621, 'attachments': '{"attachment_id":null,"file_name":null,"file_path":null}'}, {'message_id': '5387ceaa-4c0a-493e-ae69-0728c1a1e35b', 'conversation_id': 'ded63e06-b42b-47ca-9627-59df796fdd06', 'role': 'user', 'content_type': 'text', 'content': 'test1', 'created_at': 1739082937.902698, 'attachments': '{"attachment_id":null,"file_name":null,"file_path":null}'}, {'message_id': '218e6a7c-03d2-41ef-89d2-b09af5c694ba', 'conversation_id': 'ded63e06-b42b-47ca-9627-59df796fdd06', 'role': 'assistant', 'content_type': 'text', 'content': 'Hello 0\nHello 1\nHello 2\nHello 3\nHello 4\n', 'created_at': 1739082942.910374, 'attachments': '{"attachment_id":null,"file_name":null,"file_path":null}'}, {'message_id': 'e3c2026a-9b6c-458d-bfb1-78a3df1e4526', 'conversation_id': 'ded63e06-b42b-47ca-9627-59df796fdd06', 'role': 'user', 'content_type': 'text', 'content': 'test2', 'created_at': 1739082956.3585727, 'attachments': '{"attachment_id":null,"file_name":null,"file_path":null}'}, {'message_id': '464a67fb-e2f6-4a9d-892b-6945b479d158', 'conversation_id': 'ded63e06-b42b-47ca-9627-59df796fdd06', 'role': 'assistant', 'content_type': 'text', 'content': 'Hello 0\nHello 1\nHello 2\nHello 3\nHello 4\n', 'created_at': 1739082961.3697152, 'attachments': '{"attachment_id":null,"file_name":null,"file_path":null}'}, {'message_id': 'f33902d1-33c4-4b07-9225-1e379121326f', 'conversation_id': 'ded63e06-b42b-47ca-9627-59df796fdd06', 'role': 'system', 'content_type': 'text', 'content': 'pikachoo again', 'created_at': 1739082982.2270617, 'attachments': '{"attachment_id":null,"file_name":null,"file_path":null}'}, {'message_id': 'c87af900-aef9-4112-ac93-f20ed4483e47', 'conversation_id': 'ded63e06-b42b-47ca-9627-59df796fdd06', 'role': 'user', 'content_type': 'text', 'content': 'test3', 'created_at': 1739082982.2354774, 'attachments': '{"attachment_id":null,"file_name":null,"file_path":null}'}]

    messages should be formatted to something like:
    [ { "content": "Please summarize the goals for scientists in this text:\n\nWithin three days, the intertwined cup nest of grasses was complete, featuring a canopy of overhanging grasses to conceal it. And decades later, it served as Rinkert’s portal to the past inside the California Academy of Sciences. Information gleaned from such nests, woven long ago from species in plant communities called transitional habitat, could help restore the shoreline in the future. Transitional habitat has nearly disappeared from the San Francisco Bay, and scientists need a clearer picture of its original species composition—which was never properly documented. With that insight, conservation research groups like the San Francisco Bay Bird Observatory can help guide best practices when restoring the native habitat that has long served as critical refuge for imperiled birds and animals as adjacent marshes flood more with rising sea levels. “We can’t ask restoration ecologists to plant nonnative species or to just take their best guess and throw things out there,” says Rinkert.", "role": "user" }, { "content": "Scientists are studying nests hoping to learn about transitional habitats that could help restore the shoreline of San Francisco Bay.", "role": "assistant" } ]
    if there is no attachment.

    if there are attachments, attachments need to be read and converted to base64 and added to the message content.
    in case of attachments, the user messages should be formatted to something like:
    messages=[{
            "role":
            "user",
            "content": [
                {
                    "type": "text",
                    "text": "What's in this image?"
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{image_base64}"
                    },
                },
            ],
        }],

    """
    formatted_messages = []

    for msg in messages:
        formatted_msg = {"role": msg["role"]}
        attachments = msg.get("attachments", [])

        if attachments:
            # Handle messages with attachments
            content = []
            if msg["content"]:
                content.append({"type": "text", "text": msg["content"]})

            for att in attachments:
                file_type = att.get("file_type", "").split("/")[0]
                with open(att["file_path"], "rb") as f:
                    import base64

                    file_data = base64.b64encode(f.read()).decode()

                content_type_map = {"image": "image_url", "video": "video_url", "audio": "input_audio"}

                url_key = content_type_map.get(file_type, "file_url")
                content.append({"type": url_key, url_key: {"url": f"data:{att['file_type']};base64,{file_data}"}})

            formatted_msg["content"] = content
        else:
            # Handle text-only messages
            formatted_msg["content"] = msg["content"]

        formatted_messages.append(formatted_msg)

    logger.info(f"Formatted messages: {formatted_messages}")

    db_settings = db.get_settings()
    logger.info(f"DB settings: {db_settings}")
    client = OpenAI(
        api_key=db_settings["api_key"] if db_settings["api_key"] != "" else "empty",
        base_url=db_settings["host"],
    )

    chat_completion = client.chat.completions.create(
        messages=formatted_messages,
        model=db_settings["model_name"],
        max_completion_tokens=db_settings["max_tokens"],
        temperature=db_settings["temperature"],
        top_p=db_settings["top_p"],
        stream=True,
    )

    for message in chat_completion:
        if message.choices[0].delta.content is not None:
            yield message.choices[0].delta.content


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
        settings_dict = settings.model_dump()
        db.save_settings(settings_dict)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/settings")
async def get_settings():
    try:
        settings = db.get_settings()
        # Return default settings if none are saved
        if not settings:
            return {
                "temperature": 1.0,
                "max_tokens": 4096,
                "top_p": 0.95,
                "host": "http://localhost:8000",
                "model_name": "meta-llama/Llama-3.2-1B-Instruct",
                "api_key": "",
            }
        return settings
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/settings/defaults")
async def get_default_settings():
    return {
        "temperature": 1.0,
        "max_tokens": 4096,
        "top_p": 0.95,
        "host": "http://localhost:8000",
        "model_name": "meta-llama/Llama-3.2-1B-Instruct",
        "api_key": "",
    }


import re
import time


def generate_safe_filename(original_filename: str) -> str:
    """Generate a safe filename with timestamp to prevent collisions."""
    # Get timestamp
    timestamp = time.strftime("%Y%m%d_%H%M%S")

    # Get file extension
    ext = Path(original_filename).suffix

    # Get base name and sanitize it
    base = Path(original_filename).stem
    # Remove special characters and spaces
    base = re.sub(r"[^\w\-_]", "_", base)

    # Create new filename
    return f"{base}_{timestamp}{ext}"


@app.get("/get_system_prompt", response_class=JSONResponse)
async def get_system_prompt(conversation_id: str = None):
    try:
        if conversation_id:
            history = db.get_conversation_history(conversation_id)
            if history:
                system_role_messages = [m for m in history if m["role"] == "system"]
                last_system_message = (
                    system_role_messages[-1]["content"] if system_role_messages else "You are a helpful assistant."
                )
                return {"system_prompt": last_system_message}

        # Default system prompt for new conversations or when no conversation_id is provided
        return {"system_prompt": "You are a helpful assistant."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/chat", response_class=StreamingResponse)
async def chat(
    message: str = Form(...),
    system_prompt: str = Form(...),
    conversation_id: str = Form(...),  # Now required
    files: List[UploadFile] = File(None),
):
    try:
        logger.info(f"Chat request: message='{message}' conv_id={conversation_id} system_prompt='{system_prompt}'")

        # Verify conversation exists
        history = db.get_conversation_history(conversation_id)
        logger.info(history)
        if history:
            system_role_messages = [m for m in history if m["role"] == "system"]
            last_system_message = system_role_messages[-1]["content"] if system_role_messages else ""
            if last_system_message != system_prompt:
                db.add_message(conversation_id=conversation_id, role="system", content=system_prompt)

        # Handle multiple file uploads
        file_info_list = []
        if files:
            for file in files:
                if file is None:
                    continue

                # Get file size by reading the file into memory
                contents = await file.read()
                file_size = len(contents)

                # Generate safe unique filename
                safe_filename = generate_safe_filename(file.filename)
                temp_file = TEMP_DIR / safe_filename

                try:
                    # Save uploaded file
                    with open(temp_file, "wb") as f:
                        f.write(contents)
                    file_info = {
                        "name": file.filename,  # Original name for display
                        "path": str(temp_file),  # Path to saved file
                        "type": file.content_type,
                        "size": file_size,
                    }
                    file_info_list.append(file_info)
                    logger.info(f"Saved uploaded file: {temp_file} ({file_size} bytes)")
                except Exception as e:
                    logger.error(f"Failed to save uploaded file: {e}")
                    raise HTTPException(status_code=500, detail=f"Failed to process uploaded file: {str(e)}")

        if not history:
            db.add_message(conversation_id=conversation_id, role="system", content=system_prompt)

        db.add_message(
            conversation_id=conversation_id,
            role="user",
            content=message,
            attachments=file_info_list if file_info_list else None,
        )

        # get updated conversation history
        history = db.get_conversation_history(conversation_id)
        logger.info(f"Conversation history: {history}")

        async def process_and_stream():
            full_response = ""
            if file_info_list:
                files_str = ", ".join(f"'{f['name']}'" for f in file_info_list)
                acknowledgment = f"I received your message and the following files: {files_str}\n"
                full_response += acknowledgment
                for char in acknowledgment:
                    yield char
                    await asyncio.sleep(0)  # Allow other tasks to run

            async for chunk in text_streamer(history):
                full_response += chunk
                yield chunk
                await asyncio.sleep(0)  # Ensure chunks are flushed immediately

            # Store the complete response
            db.add_message(conversation_id=conversation_id, role="assistant", content=full_response)

            # Generate and store summary after assistant's response
            try:
                summary_messages = [
                    {"role": "system", "content": "summarize in less than 50 characters"},
                    {"role": "user", "content": str([history[-1], {"role": "assistant", "content": full_response}])},
                ]
                summary = ""
                async for chunk in text_streamer(summary_messages):
                    summary += chunk
                db.update_conversation_summary(conversation_id, summary.strip())
            except Exception as e:
                logger.error(f"Failed to generate summary: {e}")

        return StreamingResponse(
            process_and_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # Disable Nginx buffering
            },
        )

    except Exception as e:
        logger.error(f"Error in chat endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/conversations/{conversation_id}/summary")
async def update_conversation_summary(conversation_id: str, summary: str = Form(...)):
    try:
        db.update_conversation_summary(conversation_id, summary)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
