import os
import sqlite3
import time
import uuid
from datetime import datetime
from typing import Dict, List, Optional


_DB = """
CREATE TABLE conversations (
    conversation_id TEXT PRIMARY KEY,
    created_at REAL DEFAULT (strftime('%s.%f', 'now')),
    last_updated REAL DEFAULT (strftime('%s.%f', 'now'))
);

CREATE TABLE messages (
    message_id TEXT PRIMARY KEY,
    conversation_id TEXT,
    role TEXT CHECK(role IN ('user', 'assistant', 'system')),
    content_type TEXT CHECK(content_type IN ('text', 'image', 'audio', 'video', 'file')),
    content TEXT,
    created_at REAL DEFAULT (strftime('%s.%f', 'now')),
    FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id)
);

CREATE TABLE attachments (
    attachment_id TEXT PRIMARY KEY,
    message_id TEXT,
    file_name TEXT,
    file_path TEXT,
    file_type TEXT,
    file_size INTEGER,
    created_at REAL DEFAULT (strftime('%s.%f', 'now')),
    FOREIGN KEY (message_id) REFERENCES messages(message_id)
);

CREATE TABLE settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    temperature REAL DEFAULT 1.0,
    max_tokens INTEGER DEFAULT 4096,
    top_p REAL DEFAULT 0.95,
    host TEXT DEFAULT 'http://localhost:8000',
    model_name TEXT DEFAULT 'meta-llama/Llama-3.2-1B-Instruct',
    api_key TEXT DEFAULT '',
    updated_at REAL DEFAULT (strftime('%s.%f', 'now'))
);

-- Insert default settings
INSERT INTO settings (temperature, max_tokens, top_p, host, model_name, api_key)
VALUES (1.0, 4096, 0.95, 'http://localhost:8000', 'meta-llama/Llama-3.2-1B-Instruct', 'YOUR_API_KEY');
"""


_SYSTEM_PROMPT = """
You are an AI assistant. You answer the user's questions and provide helpful information.
"""


class ChatDatabase:
    def __init__(self, db_path: str = "chatbot.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        db_exists = os.path.exists(self.db_path)

        with sqlite3.connect(self.db_path) as conn:
            if not db_exists:
                conn.executescript(_DB)
            else:
                # Check if tables exist
                tables = conn.execute(
                    """SELECT name FROM sqlite_master 
                       WHERE type='table' AND 
                       name IN ('conversations', 'messages', 'attachments', 'settings')"""
                ).fetchall()
                if len(tables) < 4:
                    conn.executescript(_DB)

    def create_conversation(self) -> str:
        conversation_id = str(uuid.uuid4())
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT INTO conversations (conversation_id) VALUES (?)", (conversation_id,))
        return conversation_id

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        content_type: str = "text",
        attachments: Optional[List[Dict]] = None,
    ) -> str:
        message_id = str(uuid.uuid4())
        current_time = time.time()

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO messages 
                   (message_id, conversation_id, role, content_type, content, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (message_id, conversation_id, role, content_type, content, current_time),
            )

            conn.execute(
                """UPDATE conversations 
                   SET last_updated = ?
                   WHERE conversation_id = ?""",
                (current_time, conversation_id),
            )

            if attachments:
                for att in attachments:
                    conn.execute(
                        """INSERT INTO attachments 
                           (attachment_id, message_id, file_name, file_path, file_type, file_size, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (
                            str(uuid.uuid4()),
                            message_id,
                            att["name"],
                            att["path"],
                            att["type"],
                            att["size"],
                            current_time,
                        ),
                    )

        return message_id

    def get_conversation_history(self, conversation_id: str) -> List[Dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            messages = conn.execute(
                """SELECT m.*, a.attachment_id, a.file_name, a.file_path, a.file_type, a.file_size
                   FROM messages m
                   LEFT JOIN attachments a ON m.message_id = a.message_id
                   WHERE m.conversation_id = ?
                   ORDER BY m.created_at ASC""",
                (conversation_id,),
            ).fetchall()

        # Group attachments by message_id
        message_dict = {}
        for row in messages:
            message_id = row["message_id"]
            if message_id not in message_dict:
                message_dict[message_id] = {
                    key: row[key]
                    for key in ["message_id", "conversation_id", "role", "content_type", "content", "created_at"]
                }
                message_dict[message_id]["attachments"] = []

            if row["attachment_id"]:
                message_dict[message_id]["attachments"].append(
                    {
                        "attachment_id": row["attachment_id"],
                        "file_name": row["file_name"],
                        "file_path": row["file_path"],
                        "file_type": row["file_type"],
                        "file_size": row["file_size"],
                    }
                )

        return list(message_dict.values())

    def delete_conversation(self, conversation_id: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """DELETE FROM attachments 
                   WHERE message_id IN (
                       SELECT message_id FROM messages WHERE conversation_id = ?
                   )""",
                (conversation_id,),
            )
            conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
            conn.execute("DELETE FROM conversations WHERE conversation_id = ?", (conversation_id,))

    def get_all_conversations(self) -> List[Dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            conversations = conn.execute(
                """SELECT c.*, 
                   COUNT(m.message_id) as message_count,
                   MAX(m.created_at) as last_message_at
                   FROM conversations c
                   LEFT JOIN messages m ON c.conversation_id = m.conversation_id
                   GROUP BY c.conversation_id
                   ORDER BY c.created_at ASC"""
            ).fetchall()

        return [dict(conv) for conv in conversations]

    def save_settings(self, settings: Dict) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            current_time = time.time()
            conn.execute(
                """
                UPDATE settings 
                SET temperature = ?,
                    max_tokens = ?,
                    top_p = ?,
                    host = ?,
                    model_name = ?,
                    api_key = ?,
                    updated_at = ?
                WHERE id = 1
            """,
                (
                    settings.get("temperature", 1.0),
                    settings.get("max_tokens", 4096),
                    settings.get("top_p", 0.95),
                    settings.get("host", "http://localhost:8000"),
                    settings.get("model_name", "meta-llama/Llama-3.2-1B-Instruct"),
                    settings.get("api_key", ""),
                    current_time,
                ),
            )
        return True

    def get_settings(self) -> Dict:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            settings = conn.execute("SELECT * FROM settings WHERE id = 1").fetchone()
            return dict(settings) if settings else {}


if __name__ == "__main__":
    db = ChatDatabase()

    # Create 10 sample conversations
    conversations = []
    for i in range(10):
        conv_id = db.create_conversation()
        conversations.append(conv_id)

        # Different conversation patterns with at least 3 rounds
        if i == 0:
            db.add_message(conv_id, "system", "You are a helpful coding assistant")
            db.add_message(conv_id, "user", "How do I write a Python function?")
            db.add_message(
                conv_id,
                "assistant",
                'To write a Python function, use the "def" keyword followed by the function name and parameters.',
            )
            db.add_message(conv_id, "user", "Can you show me an example?")
            db.add_message(
                conv_id, "assistant", 'Here\'s a simple example:\ndef greet(name):\n    return f"Hello, {name}!"'
            )
            db.add_message(conv_id, "user", "How do I call this function?")
            db.add_message(conv_id, "assistant", 'You can call it like this: result = greet("John")')
        elif i == 1:
            db.add_message(conv_id, "system", "You are a math tutor")
            db.add_message(conv_id, "user", "Can you help me with calculus?")
            db.add_message(
                conv_id, "assistant", "Of course! What specific topic in calculus would you like to learn about?"
            )
            db.add_message(conv_id, "user", "How do I find derivatives?")
            db.add_message(
                conv_id, "assistant", "Let's start with the power rule: for x^n, the derivative is n*x^(n-1)"
            )
            db.add_message(conv_id, "user", "What's the derivative of x²?")
            db.add_message(conv_id, "assistant", "Using the power rule, the derivative of x² is 2x")
        elif i == 2:
            db.add_message(conv_id, "system", "You are a writing assistant")
            db.add_message(conv_id, "user", "How do I write a good introduction?")
            db.add_message(
                conv_id, "assistant", "Start with a hook, provide context, and end with a clear thesis statement."
            )
            db.add_message(conv_id, "user", "What makes a good hook?")
            db.add_message(
                conv_id,
                "assistant",
                "A good hook can be a surprising fact, question, quote, or anecdote that grabs attention.",
            )
            db.add_message(conv_id, "user", "Can you give an example?")
            db.add_message(
                conv_id,
                "assistant",
                'Here\'s one: "Did you know that the average person spends six months of their lifetime waiting for red lights to turn green?"',
            )
        elif i == 3:
            db.add_message(conv_id, "system", "You are a SQL expert")
            db.add_message(conv_id, "user", "How do I join tables?")
            db.add_message(
                conv_id,
                "assistant",
                "You can use INNER JOIN, LEFT JOIN, RIGHT JOIN, or FULL JOIN depending on your needs.",
            )
            db.add_message(conv_id, "user", "What's the difference between INNER and LEFT JOIN?")
            db.add_message(
                conv_id,
                "assistant",
                "INNER JOIN returns only matching rows, while LEFT JOIN returns all rows from the left table and matching rows from the right.",
            )
            db.add_message(conv_id, "user", "Can you show an example?")
            db.add_message(
                conv_id,
                "assistant",
                "Here's an example: SELECT users.name, orders.order_id FROM users LEFT JOIN orders ON users.id = orders.user_id",
            )
        elif i == 4:
            db.add_message(conv_id, "system", "You are a git expert")
            db.add_message(conv_id, "user", "How do I undo changes?")
            db.add_message(
                conv_id,
                "assistant",
                "There are several ways: git reset, git revert, or git checkout depending on your needs.",
            )
            db.add_message(conv_id, "user", "What's the difference between reset and revert?")
            db.add_message(
                conv_id,
                "assistant",
                "git reset removes commits from history, while git revert creates new commits that undo changes.",
            )
            db.add_message(conv_id, "user", "Which one is safer?")
            db.add_message(
                conv_id, "assistant", "git revert is safer for shared repositories as it doesn't alter history."
            )
        elif i == 5:
            db.add_message(conv_id, "system", "You are a Linux expert")
            db.add_message(conv_id, "user", "How do I find files?")
            db.add_message(conv_id, "assistant", 'You can use the "find" or "locate" command to search for files.')
            db.add_message(conv_id, "user", "What's the difference between them?")
            db.add_message(
                conv_id,
                "assistant",
                "find searches in real-time but is slower, locate uses a database and is faster but needs updating.",
            )
            db.add_message(conv_id, "user", "How do I update locate database?")
            db.add_message(conv_id, "assistant", 'Use the command "sudo updatedb" to update the locate database.')
        elif i == 6:
            db.add_message(conv_id, "system", "You are a Docker expert")
            db.add_message(conv_id, "user", "How do I create a container?")
            db.add_message(conv_id, "assistant", 'Use "docker run" command followed by the image name.')
            db.add_message(conv_id, "user", "How do I list running containers?")
            db.add_message(
                conv_id,
                "assistant",
                'Use "docker ps" to list running containers, or "docker ps -a" to see all containers.',
            )
            db.add_message(conv_id, "user", "How do I stop a container?")
            db.add_message(conv_id, "assistant", 'Use "docker stop container_id" to stop a running container.')
        elif i == 7:
            db.add_message(conv_id, "system", "You are a JavaScript expert")
            db.add_message(conv_id, "user", "What are promises?")
            db.add_message(
                conv_id, "assistant", "Promises are objects representing eventual completion of async operations."
            )
            db.add_message(conv_id, "user", "How do I create a promise?")
            db.add_message(conv_id, "assistant", "Use new Promise((resolve, reject) => { ... }) to create a promise.")
            db.add_message(conv_id, "user", "How do I handle errors?")
            db.add_message(
                conv_id, "assistant", "Use .catch() method or try/catch with async/await to handle promise errors."
            )
        elif i == 8:
            db.add_message(conv_id, "system", "You are a network expert")
            db.add_message(conv_id, "user", "What is DNS?")
            db.add_message(conv_id, "assistant", "DNS (Domain Name System) translates domain names to IP addresses.")
            db.add_message(conv_id, "user", "How does DNS resolution work?")
            db.add_message(
                conv_id,
                "assistant",
                "It starts with local cache, then queries root servers, TLD servers, and authoritative servers.",
            )
            db.add_message(conv_id, "user", "What are DNS record types?")
            db.add_message(
                conv_id,
                "assistant",
                "Common types include A (address), CNAME (alias), MX (mail), and TXT (text) records.",
            )
        else:
            db.add_message(conv_id, "system", "You are a security expert")
            db.add_message(conv_id, "user", "What is XSS?")
            db.add_message(
                conv_id, "assistant", "XSS (Cross-Site Scripting) allows attackers to inject malicious scripts."
            )
            db.add_message(conv_id, "user", "How can I prevent XSS?")
            db.add_message(
                conv_id, "assistant", "Use input validation, output encoding, and Content Security Policy (CSP)."
            )
            db.add_message(conv_id, "user", "What's the difference between reflected and stored XSS?")
            db.add_message(
                conv_id,
                "assistant",
                "Reflected XSS is in the request, stored XSS is saved in the database and affects multiple users.",
            )

        print(f"Created conversation {i+1} with ID: {conv_id}")
