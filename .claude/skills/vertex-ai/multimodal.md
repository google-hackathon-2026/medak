# Multimodal Inputs

Send text, images, video, audio, and PDFs to Gemini models.

## Supported Input Types

| Type | Formats | How to Pass |
|------|---------|-------------|
| Text | Plain text | String in `contents` |
| Image | JPEG, PNG, WebP, GIF | `Part.from_uri()`, `Part.from_data()`, or `fileData` |
| Video | MP4, AVI, MOV, MKV | `Part.from_uri()` with GCS URI |
| Audio | MP3, WAV, FLAC, OGG | `Part.from_uri()` with GCS URI |
| PDF | PDF files | `Part.from_uri()` with GCS URI |

## Python — Image from GCS

```python
from google import genai
from google.genai.types import HttpOptions, Part

client = genai.Client(http_options=HttpOptions(api_version="v1"))
response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=[
        "What is shown in this image?",
        Part.from_uri(
            file_uri="gs://bucket/image.jpg",
            mime_type="image/jpeg",
        ),
    ],
)
```

## Python — Image from bytes

```python
from google.genai.types import Part

with open("photo.jpg", "rb") as f:
    image_data = f.read()

response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=[
        "Describe this image.",
        Part.from_data(data=image_data, mime_type="image/jpeg"),
    ],
)
```

## Node.js — Image from GCS

```javascript
const image = {
  fileData: {
    fileURI: 'gs://bucket/image.jpg',
    mimeType: 'image/jpeg',
  },
};

const response = await client.models.generateContent({
  model: 'gemini-2.5-flash',
  contents: [image, 'What is shown in this image?'],
});
```

## Go — Image from GCS

```go
contents := []*genai.Content{
    {Parts: []*genai.Part{
        {Text: "What is shown in this image?"},
        {FileData: &genai.FileData{
            FileURI:  "gs://bucket/image.jpg",
            MIMEType: "image/jpeg",
        }},
    }, Role: genai.RoleUser},
}

resp, _ := client.Models.GenerateContent(ctx, "gemini-2.5-flash", contents, nil)
```

## REST — Image from GCS

```bash
curl -X POST \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  -H "Content-Type: application/json" \
  "https://aiplatform.googleapis.com/v1/projects/${PROJECT}/locations/global/publishers/google/models/gemini-2.5-flash:generateContent" \
  -d '{
    "contents": [{
      "role": "user",
      "parts": [
        {"text": "Describe this image"},
        {"fileData": {"fileUri": "gs://bucket/image.jpg", "mimeType": "image/jpeg"}}
      ]
    }]
  }'
```

## Sampling Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `temperature` | varies | 0 = deterministic, 0.4 = balanced, 1.0+ = creative |
| `top_p` | varies | Lower = more focused, higher = more varied |

## Best Practices

1. **Describe before analyzing**: Ask the model to describe image contents before complex tasks
2. **Be explicit**: Specify exactly what you want extracted or analyzed
3. **Point to regions**: Direct attention to relevant parts of images
4. **Few-shot examples**: Include examples of desired input/output pairs
5. **Step-by-step**: Break complex visual tasks into sequential steps
6. **Diagnose failures**: If results are wrong, check if the model understood the image vs. failed at reasoning
