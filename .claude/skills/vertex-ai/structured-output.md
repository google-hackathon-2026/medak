# Structured Output / Controlled Generation

Constrain model outputs to specific JSON schemas or enum values for consistently formatted responses.

## Supported Models

- Gemini 3.1 Flash-Lite, 3.1 Pro, 3 Flash (preview)
- Gemini 2.5 Pro/Flash/Flash-Lite
- DeepSeek R1-0528, Llama 4 Maverick/Scout, Llama 3.3

## Response MIME Types

| MIME Type | Description |
|-----------|-------------|
| `application/json` | Standard JSON output constrained by schema |
| `text/x.enum` | Single string value from predefined list |

## Schema Field Types

| Field | Description |
|-------|-------------|
| `type` | STRING, OBJECT, ARRAY, INTEGER, BOOLEAN, NUMBER |
| `properties` | Field definitions (for OBJECT) |
| `required` | Mandatory fields array |
| `enum` | Constrained string values |
| `items` | Array element schema |
| `description` | Field documentation |
| `nullable` | Allow null values (reduces hallucinations) |
| `minimum`, `maximum` | Numeric bounds |
| `minItems`, `maxItems` | Array size constraints |
| `format` | date, date-time, duration, time |
| `propertyOrdering` | Force generation sequence (non-standard) |
| `anyOf` | Alternative schemas |

## Python — JSON Schema

```python
from google import genai

response_schema = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "recipe_name": {"type": "STRING"},
            "ingredients": {
                "type": "ARRAY",
                "items": {"type": "STRING"}
            },
        },
        "required": ["recipe_name", "ingredients"],
    },
}

client = genai.Client()
response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents="List cookie recipes.",
    config={
        "response_mime_type": "application/json",
        "response_schema": response_schema,
    },
)
# response.text is valid JSON matching the schema
```

## Python — Enum Constraint

```python
from google.genai.types import GenerateContentConfig

config = GenerateContentConfig(
    response_mime_type="text/x.enum",
    response_schema={
        "type": "STRING",
        "enum": ["Percussion", "String", "Woodwind", "Brass", "Keyboard"],
    },
)

response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents="Classify a piano.",
    config=config,
)
# response.text will be exactly one of the enum values
```

## REST API

```json
{
  "contents": [{"role": "user", "parts": [{"text": "List cookie recipes."}]}],
  "generation_config": {
    "responseMimeType": "application/json",
    "responseSchema": {
      "type": "ARRAY",
      "items": {
        "type": "OBJECT",
        "properties": {
          "recipe_name": {"type": "STRING"},
          "ingredients": {"type": "ARRAY", "items": {"type": "STRING"}}
        },
        "required": ["recipe_name", "ingredients"]
      }
    }
  }
}
```

## Important Constraints

1. **Schema counts as input tokens** — large schemas reduce available context
2. **Complex schemas** can cause `InvalidArgument: 400` errors — simplify if needed
3. **Tuned models** may have decreased quality with structured output
4. **Property ordering** in prompts must match `responseSchema` ordering
5. **Fields are optional by default** — use `required` to force population

## Best Practices

- Use clear, unambiguous field names and descriptions
- Define schema only in the schema object, not duplicated in prompts
- Use `propertyOrdering` to enforce specific generation sequence
- Make fields `nullable` to reduce hallucinations when model lacks context
- Apply `enum` constraints for classification tasks
- Use `required` strategically to force necessary fields
