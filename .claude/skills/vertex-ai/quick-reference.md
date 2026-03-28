# Quick Reference

## Install

```bash
pip install --upgrade google-genai
```

## Client initialization

```python
from google import genai
from google.genai import types as genai_types

# Option 1: API key (simpler, used in dev)
client = genai.Client(api_key="your-key")

# Option 2: Vertex AI mode (production, uses ADC)
client = genai.Client(
    vertexai=True,
    project="your-project-id",
    location="us-central1",
)
```

**Auth for Vertex AI mode:**
```bash
export GOOGLE_CLOUD_PROJECT=your-project-id
export GOOGLE_CLOUD_LOCATION=us-central1
export GOOGLE_GENAI_USE_VERTEXAI=True
gcloud auth application-default login
```

Required IAM role: `roles/aiplatform.user`

## Models

| Model | Use Case |
|-------|----------|
| `gemini-2.0-flash-live-001` | Real-time Live API sessions (audio/text streaming) |
| `gemini-2.5-flash` | Standard text/multimodal generation |
| `gemini-3-flash-preview` | Latest flash preview |
| `gemini-3-pro-image-preview` | Pro-level image generation |
| `gemini-2.5-flash-image` | Multimodal image model |
| `gemini-live-2.5-flash-native-audio` | Native audio Live API (GA) |

## Text generation

```python
from google import genai
from google.genai.types import HttpOptions

client = genai.Client(http_options=HttpOptions(api_version="v1"))
response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents="How does AI work?",
)
print(response.text)
```

## Image generation

```python
from google import genai
from google.genai.types import GenerateContentConfig, Modality
from PIL import Image
from io import BytesIO

client = genai.Client()
response = client.models.generate_content(
    model="gemini-3-pro-image-preview",
    contents="Generate an image of the Eiffel tower with fireworks.",
    config=GenerateContentConfig(
        response_modalities=[Modality.TEXT, Modality.IMAGE],
    ),
)
for part in response.candidates[0].content.parts:
    if part.text:
        print(part.text)
    elif part.inline_data:
        image = Image.open(BytesIO(part.inline_data.data))
        image.save("output.png")
```

## Image understanding

```python
from google.genai.types import Part

response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=[
        "What is shown in this image?",
        Part.from_uri(file_uri="gs://bucket/image.jpg", mime_type="image/jpeg"),
    ],
)
```

## Code execution

```python
from google.genai.types import Tool, ToolCodeExecution, GenerateContentConfig

response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents="Calculate 20th fibonacci number.",
    config=GenerateContentConfig(
        tools=[Tool(code_execution=ToolCodeExecution())],
        temperature=0,
    ),
)
print(response.executable_code)
print(response.code_execution_result)
```

## GenerateContentConfig options

| Parameter | Type | Description |
|-----------|------|-------------|
| `response_modalities` | list | Output types: TEXT, IMAGE |
| `tools` | list | Tools: code_execution, function declarations |
| `temperature` | float | 0.0 (deterministic) to 1.0+ (creative) |
| `candidate_count` | int | Number of response candidates |
| `safety_settings` | list | Content filter configurations |
| `response_mime_type` | str | `application/json` or `text/x.enum` |
| `response_schema` | dict | JSON schema for structured output |

## Node.js (if needed)

```bash
npm install @google/genai
```

```javascript
const { GoogleGenAI } = require('@google/genai');

const client = new GoogleGenAI({
  vertexai: true,
  project: process.env.GOOGLE_CLOUD_PROJECT,
  location: process.env.GOOGLE_CLOUD_LOCATION || 'global',
});

const response = await client.models.generateContent({
  model: 'gemini-2.5-flash',
  contents: 'How does AI work?',
});
console.log(response.text);
```

## REST API

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  "https://aiplatform.googleapis.com/v1/projects/${GOOGLE_CLOUD_PROJECT}/locations/${GOOGLE_CLOUD_LOCATION}/publishers/google/models/gemini-2.5-flash:generateContent" \
  -d '{
    "contents": {
      "role": "user",
      "parts": { "text": "Explain how AI works" }
    }
  }'
```

## GCP setup (from scratch)

1. Create/select Google Cloud project
2. Enable billing
3. Enable Vertex AI API: `gcloud services enable aiplatform.googleapis.com`
4. Install Google Cloud CLI
5. `gcloud init` and `gcloud auth application-default login`
6. Grant `roles/aiplatform.user` IAM role
7. Set environment variables
