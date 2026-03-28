# Gemini Live API

Real-time, low-latency bidirectional streaming via stateful WebSocket connections. This is the core of this project's AI agents — both User Agent and Dispatch Agent use Live sessions.

## Models

| Model | Status | Use Case |
|-------|--------|----------|
| `gemini-2.0-flash-live-001` | GA | Used by this project for Live sessions |
| `gemini-live-2.5-flash-native-audio` | GA | Native audio voice agents (24 languages) |

## Protocol specs

- **Connection**: Stateful WebSocket (WSS)
- **Audio input**: 16-bit PCM, 16kHz, mono, little-endian
- **Audio output**: 16-bit PCM, 24kHz, mono, little-endian
- **Video input**: JPEG frames, ~1 FPS
- **Text**: Bidirectional

## Complete Live session pattern (from this codebase)

This is the pattern used by `user_agent.py` and `dispatch_agent.py`:

```python
from google import genai
from google.genai import types as genai_types

# 1. Create client
client = genai.Client(api_key="your-key")
# or: genai.Client(vertexai=True, project="...", location="...")

# 2. Define tools (function declarations)
tool_declarations = genai_types.Tool(
    function_declarations=[
        genai_types.FunctionDeclaration(
            name="my_tool",
            description="What this tool does",
            parameters=genai_types.Schema(
                type="OBJECT",
                properties={
                    "param1": genai_types.Schema(type="STRING"),
                },
                required=["param1"],
            ),
        ),
    ]
)

# 3. Configure the Live session
config = genai_types.LiveConnectConfig(
    response_modalities=["TEXT"],          # or ["AUDIO", "TEXT"] for voice
    system_instruction=genai_types.Content(
        parts=[genai_types.Part(text="Your system prompt here")]
    ),
    tools=[tool_declarations],
)

# 4. Connect and run the event loop
async with client.aio.live.connect(
    model="gemini-2.0-flash-live-001",
    config=config,
) as session:
    # Send initial context
    await session.send(input="Initial message to the model", end_of_turn=True)

    # Process responses
    async for response in session.receive():
        # Handle tool calls
        if response.tool_call:
            for fc in response.tool_call.function_calls:
                result = await execute_tool(fc.name, fc.args or {})
                await session.send(
                    input=genai_types.LiveClientToolResponse(
                        function_responses=[
                            genai_types.FunctionResponse(
                                name=fc.name,
                                response={"result": result},
                            )
                        ]
                    )
                )

        # Handle text output
        if response.text:
            print(response.text)
```

## Key types

### LiveConnectConfig

```python
genai_types.LiveConnectConfig(
    response_modalities=["TEXT"],              # ["TEXT"], ["AUDIO"], or ["AUDIO", "TEXT"]
    system_instruction=genai_types.Content(    # System prompt
        parts=[genai_types.Part(text="...")]
    ),
    tools=[tool_declarations],                 # List of genai_types.Tool objects
)
```

### Sending text

```python
await session.send(input="your message", end_of_turn=True)
```

The `end_of_turn=True` flag tells the model it's the model's turn to respond. Without it, the model waits for more input.

### Sending audio

```python
# Raw PCM bytes, 16kHz mono 16-bit little-endian
await session.send(input=audio_bytes)
```

### Sending tool responses

```python
await session.send(
    input=genai_types.LiveClientToolResponse(
        function_responses=[
            genai_types.FunctionResponse(
                name="tool_name",
                response={"result": "tool output"},
            )
        ]
    )
)
```

### Processing responses

```python
async for response in session.receive():
    if response.tool_call:
        # Model wants to call a tool
        for fc in response.tool_call.function_calls:
            fc.name    # str: function name
            fc.args    # dict: arguments (may be None)

    if response.text:
        # Model generated text
        pass

    if response.audio:
        # Model generated audio (when response_modalities includes "AUDIO")
        pass
```

## Capabilities

- **Voice Activity Detection (VAD)**: Automatic turn-taking with barge-in interruption — no manual endpointing needed
- **Function calling**: Works within live sessions for real-time tool use
- **Audio transcriptions**: Both user input and model output
- **Affective dialog**: Adapts response style to user's tone
- **Multilingual**: 24 languages with seamless switching
- **Proactive audio** (Preview): Controlled response timing

## Partner integrations (WebRTC)

Pre-integrated platforms for telephony: **Daily**, **LiveKit**, **Twilio**, **Voximplant**

## Common patterns

### Dual-mode client init (API key vs Vertex AI)

This project supports both auth modes:

```python
if settings.google_api_key:
    client = genai.Client(api_key=settings.google_api_key)
else:
    client = genai.Client(
        vertexai=True,
        project=settings.google_cloud_project,
        location=settings.google_cloud_location,
    )
```

### Tool handler dispatch pattern

Map tool names to async handlers, dispatch on function call name:

```python
tool_handlers = {
    "my_tool": lambda args: tools.my_tool(args["param1"]),
    "another_tool": lambda _: tools.another_tool(),
}

# In the response loop:
if response.tool_call:
    for fc in response.tool_call.function_calls:
        handler = tool_handlers.get(fc.name)
        if handler:
            result = await handler(fc.args or {})
            await session.send(
                input=genai_types.LiveClientToolResponse(
                    function_responses=[
                        genai_types.FunctionResponse(
                            name=fc.name,
                            response={"result": result},
                        )
                    ]
                )
            )
```
