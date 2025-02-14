import asyncio
import base64
import os
import re
import tempfile
import time
import requests
import json
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from openai import OpenAI
from pydantic import BaseModel

from aiaio import __version__, logger
from aiaio.db import ChatDatabase
from aiaio.prompts import SUMMARY_PROMPT


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


class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                # If sending fails, we'll handle it in the main websocket route
                pass


manager = ConnectionManager()


class FileAttachment(BaseModel):
    """
    Pydantic model for handling file attachments in messages.

    Attributes:
        name (str): Name of the file
        type (str): MIME type of the file
        data (str): Base64 encoded file data
    """

    name: str
    type: str
    data: str


class MessageContent(BaseModel):
    """
    Pydantic model for message content including optional file attachments.

    Attributes:
        text (str): The text content of the message
        files (List[FileAttachment]): Optional list of file attachments
    """

    text: str
    files: Optional[List[FileAttachment]] = None


class ChatInput(BaseModel):
    """
    Pydantic model for chat input data.

    Attributes:
        message (str): The user's message content
        system_prompt (str): Instructions for the AI model
        conversation_id (str, optional): ID of the conversation
    """

    message: str
    system_prompt: str
    conversation_id: Optional[str] = None


class MessageInput(BaseModel):
    """
    Pydantic model for message input data.

    Attributes:
        role (str): The role of the message sender (e.g., 'user', 'assistant', 'system')
        content (str): The message content
        content_type (str): Type of content, defaults to "text"
        attachments (List[Dict], optional): List of file attachments
    """

    role: str
    content: str
    content_type: str = "text"
    attachments: Optional[List[Dict]] = None


class SettingsInput(BaseModel):

    """
    Pydantic model for AI model settings.

    Attributes:
        temperature (float): Controls randomness in responses
        max_tokens (int): Maximum length of generated responses
        top_p (float): Controls diversity via nucleus sampling
        host (str): API endpoint URL
        model_name (str): Name of the AI model to use
        api_key (str): Authentication key for the API
    """

    temperature: Optional[float] = 1.0
    max_tokens: Optional[int] = 4096
    top_p: Optional[float] = 0.95
    host: Optional[str] = "http://localhost:8000/v1"
    model_name: Optional[str] = "meta-llama/Llama-3.2-1B-Instruct"
    api_key: Optional[str] = ""


async def text_streamer(messages: List[Dict[str, str]]):
    """
    Stream text responses from the AI model.

    Args:
        messages (List[Dict[str, str]]): List of message dictionaries containing role and content

    Yields:
        str: Chunks of generated text from the AI model
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
                    file_data = base64.b64encode(f.read()).decode()

                content_type_map = {"image": "image_url", "video": "video_url", "audio": "input_audio"}

                url_key = content_type_map.get(file_type, "file_url")
                content.append({"type": url_key, url_key: {"url": f"data:{att['file_type']};base64,{file_data}"}})

            formatted_msg["content"] = content
        else:
            # Handle text-only messages
            formatted_msg["content"] = msg["content"]

        formatted_messages.append(formatted_msg)

    db_settings = db.get_settings()
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

    # db_settings['host'] = 'xxx'
    # db_settings['token'] = 'xxx'
    # db_settings['model_name'] = 'default'
    #
    # url = f"{db_settings['host']}/v1/chat/completions"
    # headers = {
    #     "Authorization": db_settings['token'],
    #     "Content-Type": "application/json",
    # }
    # payload = {
    #     "model": db_settings["model_name"],
    #     "messages": formatted_messages,
    #     "max_tokens": db_settings["max_tokens"],
    #     "temperature": db_settings["temperature"],
    #     "top_p": db_settings["top_p"],
    #     "stream": True,
    # }
    #
    # response = requests.post(url, headers=headers, json=payload, stream=True)
    #
    # for line in response.iter_lines():
    #     if line:
    #         try:
    #             data = line.decode("utf-8").replace("data: ", "").strip()
    #             if data and data != "[DONE]":
    #                 message = json.loads(data)
    #                 if message["choices"][0]["delta"].get("content"):
    #                     yield message["choices"][0]["delta"]["content"]
    #         except Exception as e:
    #             print(f"Error parsing response: {e}")



@app.get("/", response_class=HTMLResponse)
async def load_index(request: Request):
    """
    Serve the main application page.

    Args:
        request (Request): FastAPI request object

    Returns:
        TemplateResponse: Rendered HTML template
    """
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        },
    )


@app.get("/version")
async def version():
    """
    Get the application version.

    Returns:
        dict: Version information
    """
    return {"version": __version__}


@app.get("/conversations")
async def get_conversations():
    """
    Retrieve all conversations.

    Returns:
        dict: List of all conversations

    Raises:
        HTTPException: If database operation fails
    """
    try:
        conversations = db.get_all_conversations()
        return {"conversations": conversations}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str):
    """
    Retrieve a specific conversation's history.

    Args:
        conversation_id (str): ID of the conversation to retrieve

    Returns:
        dict: Conversation messages

    Raises:
        HTTPException: If conversation not found or operation fails
    """
    try:
        history = db.get_conversation_history(conversation_id)
        if not history:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return {"messages": history}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/create_conversation")
async def create_conversation():
    """
    Create a new conversation.

    Returns:
        dict: New conversation ID

    Raises:
        HTTPException: If creation fails
    """
    try:
        conversation_id = db.create_conversation()
        # Broadcast update to all connected clients
        await manager.broadcast({"type": "conversation_created", "conversation_id": conversation_id})
        return {"conversation_id": conversation_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/conversations/{conversation_id}/messages")
async def add_message(conversation_id: str, message: MessageInput):
    """
    Add a message to a conversation.

    Args:
        conversation_id (str): Target conversation ID
        message (MessageInput): Message data to add

    Returns:
        dict: Added message ID

    Raises:
        HTTPException: If operation fails
    """
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
    """
    Delete a conversation.

    Args:
        conversation_id (str): ID of conversation to delete

    Returns:
        dict: Operation status

    Raises:
        HTTPException: If deletion fails
    """
    try:
        db.delete_conversation(conversation_id)
        await manager.broadcast({"type": "conversation_deleted", "conversation_id": conversation_id})
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/save_settings")
async def save_settings(settings: SettingsInput):
    """
    Save AI model settings.

    Args:
        settings (SettingsInput): Settings to save

    Returns:
        dict: Operation status

    Raises:
        HTTPException: If save operation fails
    """
    try:
        settings_dict = settings.model_dump()
        db.save_settings(settings_dict)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/settings")
async def get_settings():
    """
    Retrieve current AI model settings.

    Returns:
        dict: Current settings or defaults if none saved

    Raises:
        HTTPException: If retrieval fails
    """
    try:
        settings = db.get_settings()
        # Return default settings if none are saved
        if not settings:
            return {
                "temperature": 1.0,
                "max_tokens": 4096,
                "top_p": 0.95,
                "host": "http://localhost:8000/v1",
                "model_name": "meta-llama/Llama-3.2-1B-Instruct",
                "api_key": "",
            }
        return settings
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/settings/defaults")
async def get_default_settings():
    """
    Get default AI model settings.

    Returns:
        dict: Default settings values
    """
    return {
        "temperature": 1.0,
        "max_tokens": 4096,
        "top_p": 0.95,
        "host": "http://localhost:8000/v1",
        "model_name": "meta-llama/Llama-3.2-1B-Instruct",
        "api_key": "",
    }


def generate_safe_filename(original_filename: str) -> str:
    """
    Generate a safe filename with timestamp to prevent collisions.

    Args:
        original_filename (str): Original filename to be sanitized

    Returns:
        str: Sanitized filename with timestamp
    """
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
    """
    Get the system prompt for a conversation.

    Args:
        conversation_id (str, optional): ID of the conversation

    Returns:
        JSONResponse: System prompt text

    Raises:
        HTTPException: If retrieval fails
    """
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
    """
    Handle chat requests with support for file uploads and streaming responses.

    Args:
        message (str): User's message
        system_prompt (str): System instructions for the AI
        conversation_id (str): Unique identifier for the conversation
        files (List[UploadFile]): Optional list of uploaded files

    Returns:
        StreamingResponse: Server-sent events stream of AI responses

    Raises:
        HTTPException: If there's an error processing the request
    """
    try:
        logger.info(f"Chat request: message='{message}' conv_id={conversation_id} system_prompt='{system_prompt}'")

        # Verify conversation exists
        history = db.get_conversation_history(conversation_id)
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

        async def process_and_stream():
            """
            Inner generator function to process the chat and stream responses.

            Yields:
                str: Chunks of the AI response
            """
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

            # Broadcast update after storing the response
            await manager.broadcast(
                {
                    "type": "message_added",
                    "conversation_id": conversation_id,
                }
            )

            # Generate and store summary after assistant's response
            try:
                all_user_messages = [m["content"] for m in history if m["role"] == "user"]
                summary_messages = [
                    {"role": "system", "content": SUMMARY_PROMPT},
                    {"role": "user", "content": str(all_user_messages)},
                ]
                summary = ""
                logger.info(summary_messages)
                async for chunk in text_streamer(summary_messages):
                    summary += chunk
                db.update_conversation_summary(conversation_id, summary.strip())

                # After summary update
                await manager.broadcast(
                    {"type": "summary_updated", "conversation_id": conversation_id, "summary": summary.strip()}
                )
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
    """
    Update the summary of a conversation.

    Args:
        conversation_id (str): ID of the conversation
        summary (str): New summary text

    Returns:
        dict: Operation status

    Raises:
        HTTPException: If update fails
    """
    try:
        db.update_conversation_summary(conversation_id, summary)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Wait for any message (keepalive)
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
