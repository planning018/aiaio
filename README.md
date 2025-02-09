# aiaio (AI-AI-O)

A lightweight, privacy-focused web UI for interacting with AI models. Supports both local and remote LLM deployments through OpenAI-compatible APIs.

![Screenshot](https://github.com/abhishekkrthakur/aiaio/blob/main/ui.png?raw=true)

## Features

- 🌓 Dark/Light mode support
- 💾 Conversation history and management
- 📁 File upload and processing
- ⚙️ Configurable model settings
- 🔒 Privacy-focused (all data stays local)
- 📱 Responsive design for mobile/desktop
- 🎨 Syntax highlighting for code
- 📋 Code block copying

## Requirements

- Python 3.8+
- An OpenAI-compatible API endpoint (local or remote)

## Supported Frameworks

- vLLM
- TGI
- OpenAI
- Hugging Face 
- llama.cpp
- any other custom openai-compatible api

## Installation using pip

```bash
pip install aiaio
```

## Quick Start

1. Start the server:
```bash
aiaio app --host 127.0.0.1 --port 5000
```

2. Open your browser and navigate to `http://127.0.0.1:5000`

## Docker Usage

1. Build the Docker image:
```bash
docker build -t aiaio .
```

2. Run the container:
```bash
docker run -p 9000:9000 aiaio
```

3. Access the UI at `http://localhost:9000`

## Configuration

Configure these settings through the UI or environment variables:

- `MODEL_NAME` - LLM model to use (default: meta-llama/Llama-3.2-1B-Instruct)
- `API_HOST` - API endpoint URL
- `API_KEY` - Your API key (if required)
- `MAX_TOKENS` - Maximum tokens per response (default: 4096)
- `TEMPERATURE` - Response randomness (0-2, default: 1.0)
- `TOP_P` - Nucleus sampling parameter (0-1, default: 0.95)


## Development

```bash
# Clone the repository
git clone https://github.com/abhishekkrthakur/aiaio.git
cd aiaio

# Install in development mode
pip install -e .

# Run tests
pytest
```

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

Apache License - see LICENSE file for details

## Acknowledgements

GitHub CoPilot. Most of the code was written by CoPilot. I just pressed the keys on the keyboard.