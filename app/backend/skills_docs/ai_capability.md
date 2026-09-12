# AI Capability

## Description
AI text, image, video, audio generation, single-PDF analysis, and speech transcription guidance. Covers frontend SDK `client.ai` usage (`gentxt` / `genimg` / `genvideo` / `genaudio`), backend `AIHubService` usage, and backend endpoint patterns for PDF/document tasks.

## Guide

### AI Capability (aihub module)

When the requirement involves AI features (text generation, image analysis, auto-reply, chat, etc.):

> Note: `scribe_v2` is the default speech recognition model in `multimodal.audio_transcription`. Use it for captions, transcripts, and subtitle source text. `client.ai` currently covers generation APIs only. For `transcribe` and `analyzepdf`, call the backend endpoints via `client.apiCall.invoke`, or use `AIHubService` directly in backend code.

#### Core Feature Rules
- If AI is part of the PRIMARY user-facing feature, "the button spins and then resets" is NOT acceptable behavior. The result must either appear in the intended result state/page, or the user must see a clear error with a retry path.
- For backend business logic that depends on exact structured output, prefer NON-streaming generation so you can validate the full payload before saving state.
- Do NOT rely on a single naked `json.loads(raw_content)` call for requirement-critical structured output. Use a stricter flow: schema-focused prompt -> full output -> JSON block extraction -> required-field validation -> one repair/retry -> clear error if still invalid.
- If AI is used as a strict classifier/detector/validator for business decisions, such as face count, document structure, or suitability checks, do not treat parse failure as a normal negative result. Use a fallback path or return a retryable failure instead.
- If the frontend calls a custom `/api/v1/*` endpoint that internally chains multiple AI steps in sequence, set `client.apiCall.invoke(..., options: { timeout: 600_000 })` on that frontend request. Do not rely on the default timeout for chained AI flows.
- If the same backend request touches both `AsyncSession` and `AIHubService`, finish the current DB phase before the AI call and follow the database session boundary rules in `skills_docs/custom_api.md`.

#### Frontend-first vs Backend AI Calls
- Use frontend `client.ai.gentxt` directly when the generated text is shown directly to the user, when you want streaming UX, or when the overall feature calls `gentxt` multiple times in sequence (for example: outline -> content -> summary). Each `gentxt` call is still a single step; orchestrate the sequence on the frontend instead of hiding it behind one slow backend endpoint.
- Use backend `AIHubService` through a custom `/api/v1/*` route only when the result must be validated or transformed server-side, persisted between steps, or depends on server-only data or secrets.
- Do not default to a single backend endpoint that chains multiple `gentxt` calls in sequence. That pattern is slower to recover from, more timeout-prone, and harder to keep responsive for the user.

#### Frontend - Use Web SDK `client.ai` (preferred)

**`client.ai.gentxt(params)`**
- Required: `messages`, `model`, `stream`
- `messages[].role`: `system` / `user` / `assistant`
- `messages[].content`:
  - Text: string
  - Multimodal: `[{ type: 'text', text: '...' }, { type: 'image_url', image_url: { url: 'https://...' | 'data:image/png;base64,...' } }]`
- Streaming callbacks (when `stream: true`): `onChunk`, `onComplete`, `onError`
- Default: when calling via SDK `client.ai.gentxt`, use `stream: true` unless explicitly required otherwise
- Avoid custom backend wrapper endpoints for aihub unless necessary; if you must call a custom endpoint via `client.apiCall.invoke`, default to NON-streaming (return full content) to avoid fragile stream parsing

```typescript
// Streaming (recommended)
const result = await client.ai.gentxt({
  messages: [...],
  model: 'deepseek-v3.2',
  stream: true,
  onChunk: (chunk) => {/* chunk.content */},
  onComplete: (finalResult) => {/* finalResult.content */},
  onError: (error) => {/* error.message */},
});

// Non-streaming
const response = await client.ai.gentxt({ messages: [...], model: 'deepseek-v3.2', stream: false });
const text = response.data.content;
```

**`client.ai.genimg(params, options?)`**
- Required: `prompt`, `model`
- Optional: `size` (default `"1024x1024"`), `quality` (default `"auto"`, ignored for img2img), `n` (default `1`)
- `image` (img2img): Base64 Data URI string OR list of Base64 Data URI strings (multi-image); HTTP URL NOT allowed
  - Examples: `[subject, background]` (bg replace), `[person, clothing]` (try-on), `[content, style_ref]` (style transfer)
- Timeout: genimg may be slow; set longer timeout (e.g., `600_000` ms)
- Response: `response.data.images[0]` is URL (preferred) or base64 Data URI
- One-step-first: if one `genimg` call can solve it, do NOT split into multiple endpoints/steps; only split when quality/controllability requires it, and show progress

```typescript
const img = await client.ai.genimg(
  { prompt: 'cat', model: 'gpt-image-2', size: '1024x1024', quality: 'auto', n: 1 },
  { timeout: 600_000 }
);
const edited = await client.ai.genimg(
  { prompt: '...', model: 'gemini-3-pro-image', image: 'data:image/png;base64,...' },
  { timeout: 600_000 }
);
```

**`client.ai.genvideo(params, options?)`**
- Required: `prompt`, `model`
- Optional: `size` (default `"1280x720"`, do NOT change), `seconds` (default `"4"`, do NOT change)
- `image` (image-to-video): Base64 Data URI string as the first frame reference
- Timeout: video generation is slow; set longer timeout (e.g., `600_000` ms or more)
- Response: `response.data.url` is the CDN URL of the generated video
- Note: Video generation is async - the API polls internally until completion

```typescript
// Text-to-Video
const video = await client.ai.genvideo(
  { prompt: 'Ocean waves at sunset', model: 'wan2.6-t2v' },
  { timeout: 600_000 }
);
const videoUrl = video.data.url;

// Image-to-Video (use image as first frame)
const videoFromImage = await client.ai.genvideo(
  { prompt: 'Animate the scene', model: 'wan2.6-i2v', image: 'data:image/png;base64,...' },
  { timeout: 600_000 }
);
```

**`client.ai.genaudio(params, options?)`**
- Required: `text`, `model`
- Optional: `gender` (default `"female"`, options: `"male"` | `"female"`)
- Voice is auto-selected based on model and gender (no manual voice selection needed)
- Response: `response.data.url` is the CDN URL of the generated audio (mp3)

```typescript
const audio = await client.ai.genaudio(
  { text: 'Welcome to our website', model: 'eleven_v3', gender: 'female' },
  { timeout: 600_000 }
);
const audioUrl = audio.data.url;

// Male voice
const maleAudio = await client.ai.genaudio(
  { text: 'Product introduction', model: 'eleven_v3', gender: 'male' },
  { timeout: 600_000 }
);
```

**Speech transcription via backend endpoint**
- `client.ai` currently has no dedicated transcription helper; call `/api/v1/aihub/transcribe` with `client.apiCall.invoke`
- Required: `audio`
- Optional: `model` (default `scribe_v2`)
- `audio` supports HTTP URL, base64 data URI, or backend absolute path
- Response: `response.data.text` is the transcript
- `/api/v1/aihub/transcribe` is a JSON-only endpoint. Do NOT send `FormData`, `UploadFile`, or `multipart/form-data` to it.
- If the source is a browser `File`/`Blob`, either convert it to a base64 data URI on the frontend and send JSON to `/api/v1/aihub/transcribe`, or create a custom backend wrapper route that accepts `UploadFile`, then converts the uploaded file and calls `AIHubService.transcribe(...)` internally.
- If you create such a wrapper route for business needs like auth, DB persistence, or extra fields such as `source_type`, the frontend must call that custom route instead of calling `/api/v1/aihub/transcribe` directly.

```typescript
const transcript = await client.apiCall.invoke({
  url: '/api/v1/aihub/transcribe',
  method: 'POST',
  data: {
    audio: 'https://cdn.example.com/interview.mp3',
    model: 'scribe_v2',
  },
});
const text = transcript.data.text;
```

```typescript
// Browser File/Blob -> base64 data URI -> JSON request
const fileToDataUri = (file: File) =>
  new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });

const audioDataUri = await fileToDataUri(file);
const transcript = await client.apiCall.invoke({
  url: '/api/v1/aihub/transcribe',
  method: 'POST',
  data: {
    audio: audioDataUri,
    model: 'scribe_v2',
  },
});
```

**Single PDF analysis via backend endpoint**
- Call `/api/v1/aihub/analyzepdf` with `client.apiCall.invoke`
- Required: `pdf`, `instruction`
- Optional: `mode` (`qa` or `extract`), `page_start`, `page_end`
- `pdf` must be a base64 PDF data URI
- Timeout: PDF analysis may be slow; set request timeout to `600_000` ms (10 minutes)
- Single PDF only; the backend selects the PDF analysis model internally
- Response: `response.data.result` contains the answer or extracted Markdown

```typescript
const fileToDataUri = (file: File) =>
  new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });

const pdfDataUri = await fileToDataUri(file);
const pdfAnalysis = await client.apiCall.invoke({
  url: '/api/v1/aihub/analyzepdf',
  method: 'POST',
  data: {
    pdf: pdfDataUri,
    instruction: 'Summarize the top business risks in Chinese.',
    mode: 'extract',
    page_start: 1,
    page_end: 20,
  },
  options: {
    timeout: 600_000,
  },
});
const analysisText = pdfAnalysis.data.result;
```

#### Frontend Timeout For Chained AI Custom APIs
- If a single frontend action calls a custom backend endpoint that internally performs 2 or more AI steps in sequence, the frontend request MUST set `options.timeout` to `600_000` (600 seconds).
- Typical cases: `analyzepdf -> structured extraction`, `transcribe -> summarize -> action items`, `remove background -> white-background render -> scene render`, or any similar multi-step AI pipeline hidden behind one custom API.

```typescript
const response = await client.apiCall.invoke({
  url: '/api/v1/story/generate',
  method: 'POST',
  data: formData,
  options: {
    timeout: 600_000,
  },
});
```


#### Error Handling (Frontend)

**CRITICAL: Every error handler MUST reset the UI loading/progress state.** Never leave the UI stuck in a loading spinner after an error.

```typescript
// IMPORTANT: UI toast requires <Toaster /> mounted in App
const getErrorDetail = (error: any) =>
  error?.data?.detail || error?.response?.data?.detail || error?.message || 'Request failed';

// Non-streaming — MUST reset loading state in catch AND finally
try {
  setLoading(true);
  await client.ai.gentxt({ ..., stream: false });
} catch (e: any) {
  toast({ title: 'Error', description: getErrorDetail(e), variant: 'destructive' });
} finally {
  setLoading(false);
}

// Streaming — onError MUST reset loading state
setLoading(true);
await client.ai.gentxt({
  ...,
  stream: true,
  onComplete: () => setLoading(false),
  onError: (e) => {
    setLoading(false);
    toast({ title: 'Error', description: getErrorDetail(e), variant: 'destructive' });
  },
});
```

#### Structured Output Pattern (Backend)

```python
from fastapi import HTTPException
import json
import re

from services.aihub import AIHubService
from schemas.aihub import GenTxtRequest, ChatMessage

service = AIHubService()
request = GenTxtRequest(
    messages=[
        ChatMessage(role="system", content="Return ONLY valid JSON."),
        ChatMessage(role="user", content=prompt),
    ],
    model="gpt-5-chat",
)

response = await service.gentxt(request)
raw_content = response.content.strip()

def extract_json_block(text: str) -> str:
    if text.startswith("```"):
        match = re.search(r"```(?:json)?\n(.*?)```", text, re.DOTALL)
        if match:
            text = match.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start:end + 1]
    return text

payload_text = extract_json_block(raw_content)

try:
    payload = json.loads(payload_text)
except json.JSONDecodeError:
    repair_request = GenTxtRequest(
        messages=[
            ChatMessage(role="system", content="Fix this into valid JSON only."),
            ChatMessage(role="user", content=payload_text),
        ],
        model="gpt-5-chat",
    )
    repaired = await service.gentxt(repair_request)
    try:
        payload = json.loads(extract_json_block(repaired.content.strip()))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="AI output parsing failed. Please try again.") from exc

required_fields = ["summary", "items"]
missing = [field for field in required_fields if field not in payload]
if missing:
    raise HTTPException(status_code=500, detail=f"AI output missing fields: {', '.join(missing)}")
```

Avoid `json.loads(response.content)` as the only parsing path for requirement-critical features. That shortcut is acceptable only for throwaway prototypes or non-critical helper logic.

#### Backend - Import AIHubService directly (NOT via httpx/requests)

```python
from services.aihub import AIHubService
from schemas.aihub import GenTxtRequest, ChatMessage

service = AIHubService()
request = GenTxtRequest(
    messages=[
        ChatMessage(role="system", content="You are a summarization expert"),
        ChatMessage(role="user", content=text)
    ],
    model="deepseek-v3.2"
)

# Streaming (DEFAULT / recommended) - gentxt_stream yields plain text chunks directly
async for chunk in service.gentxt_stream(request):
    yield chunk  # chunk is plain text string

# Non-streaming (ONLY when you explicitly need a single complete payload)
response = await service.gentxt(request)
result = response.content  # string
```

**Video Generation (Backend)**
```python
from services.aihub import AIHubService
from schemas.aihub import GenVideoRequest

service = AIHubService()

# Text-to-Video
request = GenVideoRequest(
    prompt="Ocean waves at sunset",
    model="wan2.6-t2v"
    # size and seconds have safe defaults, do NOT change unless necessary
)
response = await service.genvideo(request)
video_url = response.url  # CDN URL

# Image-to-Video (use base64 data URI as first frame)
request = GenVideoRequest(
    prompt="Animate the scene",
    model="wan2.6-i2v",
    image="data:image/png;base64,..."  # or HTTP URL
)
response = await service.genvideo(request)
```

**Audio Generation (Backend)**
```python
from services.aihub import AIHubService
from schemas.aihub import GenAudioRequest

service = AIHubService()

# TTS with gender-based voice selection
request = GenAudioRequest(
    text="Welcome to our website",
    model="eleven_v3",
    gender="female"  # voice is auto-selected based on model and gender
)
response = await service.genaudio(request)
audio_url = response.url  # CDN URL
voice_used = response.voice  # actual voice name used
```

**Speech Transcription (Backend)**
```python
from services.aihub import AIHubService
from schemas.aihub import TranscribeAudioRequest

service = AIHubService()

request = TranscribeAudioRequest(
    audio="https://cdn.example.com/interview.mp3",
    model="scribe_v2",
)
response = await service.transcribe(request)
transcript_text = response.text
```

**Single PDF Analysis (Backend)**
```python
from services.aihub import AIHubService
from schemas.aihub import AnalyzePdfRequest

service = AIHubService()

request = AnalyzePdfRequest(
    pdf="data:application/pdf;base64,...",
    instruction="Summarize the main risks in Chinese.",
    mode="extract",
    page_start=1,
    page_end=20,
)
response = await service.analyze_pdf(request)
analysis_text = response.result
```
