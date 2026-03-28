---
name: vertex-ai
description: "Build apps with Vertex AI, Gemini models, and the Google GenAI SDK. Use this skill whenever code imports google.genai, @google/genai, google.genai.types, or vertexai. Also use it when the user mentions Gemini models, Vertex AI, Google AI, GenAI SDK, Gemini Live API, Gemini function calling, or needs help with real-time audio/video AI sessions. Even if the user just says 'the AI agent' or 'the Gemini part', if the codebase uses google-genai, this skill applies."
allowed-tools: Read, Grep, Edit, Write, Bash
argument-hint: [topic]
---

# Vertex AI / Google GenAI SDK

This project uses the **unified `google-genai` SDK** (not the older `google-cloud-aiplatform` or `vertexai` packages). All imports look like:

```python
from google import genai
from google.genai import types as genai_types
```

The two core patterns in this codebase are **Gemini Live sessions** (real-time bidirectional audio/text streaming) and **function calling** (tool use via `genai_types.FunctionDeclaration`). See the backend's `user_agent.py` and `dispatch_agent.py` for working examples.

## When to consult which reference

| You need to... | Read |
|----------------|------|
| Set up the SDK, authenticate, pick a model | [quick-reference.md](quick-reference.md) |
| Build a real-time audio/video session (Live API) | [live-api.md](live-api.md) |
| Declare tools the model can call | [function-calling.md](function-calling.md) |
| Force JSON or enum output from the model | [structured-output.md](structured-output.md) |
| Send images, video, audio, or PDFs as input | [multimodal.md](multimodal.md) |

## Key decisions

- **Model for Live sessions**: `gemini-2.0-flash-live-001` — this is what the project uses for real-time streaming
- **Model for standard generation**: `gemini-2.5-flash` for most tasks
- **Client init**: Use `genai.Client(api_key=...)` for API key auth, or `genai.Client(vertexai=True, project=..., location=...)` for Vertex AI mode
- **Live session config**: Use `genai_types.LiveConnectConfig` with `response_modalities`, `system_instruction`, and `tools`
- **Function declarations**: Use `genai_types.Tool(function_declarations=[...])` with `genai_types.FunctionDeclaration` and `genai_types.Schema`
- **Tool responses**: Send back via `genai_types.LiveClientToolResponse` wrapping `genai_types.FunctionResponse`
- **Temperature**: 0 for deterministic (function calling, structured output), 0.4+ for creative

## Common mistakes to avoid

- Don't import from `vertexai.generative_models` — this project uses `google.genai`
- Don't use `GenerativeModel(model_name=...)` — use `client.models.generate_content(model=...)` or `client.aio.live.connect(model=...)`
- Don't forget `end_of_turn=True` when sending text to a Live session
- Don't mix sync and async — Live sessions use `client.aio.live.connect()` (async)
