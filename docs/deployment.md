# Deployment & Configuration

## Environment Variables

All configuration is via `.env` file (loaded by `python-dotenv`).

### Required

| Variable | Example | Purpose |
|---|---|---|
| `AZURE_VOICE_LIVE_ENDPOINT` | `https://my-resource.services.ai.azure.com` | Azure AI Foundry endpoint with Voice Live API access |
| `VOICE_LIVE_MODEL` | `gpt-4.1-mini` | Model deployment name |

### Authentication (one of these)

| Variable | Example | Purpose |
|---|---|---|
| `AZURE_VOICE_LIVE_API_KEY` | `abc123...` | API key auth (simplest) |
| *(leave blank)* | | Uses Azure CLI credential (`az login`) |
| `AZURE_USER_ASSIGNED_IDENTITY_CLIENT_ID` | `guid` | Managed Identity (for Azure-hosted deployment) |

**Priority:** API key → Managed Identity → Azure CLI.

### Optional — BYO LLM

Use when the LLM is deployed on a **different** Foundry resource than Voice Live.

| Variable | Example | Purpose |
|---|---|---|
| `BYOM_PROFILE` | `byom-azure-openai-chat-completion` | BYOM routing profile |
| `FOUNDRY_RESOURCE_OVERRIDE` | `https://llm-resource.services.ai.azure.com` | LLM's Foundry endpoint |

**Supported BYOM profiles:**
- `byom-azure-openai-chat-completion` — Azure OpenAI (chat)
- `byom-azure-openai-realtime` — Azure OpenAI (realtime)
- `byom-foundry-anthropic-messages` — Anthropic Claude via Foundry
- *(empty)* — managed (Voice Live's own model, default)

### Application Settings

| Variable | Default | Purpose |
|---|---|---|
| `APP_HOST` | `0.0.0.0` | Server bind address |
| `APP_PORT` | `8000` | Server port |
| `LOG_LEVEL` | `INFO` | Python logging level |

---

## Local Development

### Prerequisites

```bash
python --version    # 3.11+
az --version        # Azure CLI (if not using API key)
az login            # Authenticate (if not using API key)
```

### Setup

```bash
# Clone
git clone <repo-url>
cd VirtualRM

# Virtual environment
python -m venv server/.venv
server\.venv\Scripts\activate    # Windows
source server/.venv/bin/activate  # Linux/macOS

# Dependencies
pip install -r requirements.txt

# Environment
cp .env.sample .env
# Edit .env with your Azure credentials

# Database
cd server
python seed_db.py

# Run
python app.py
```

Server starts at `http://localhost:8000`.

### Development Tips

- **Logs:** Set `LOG_LEVEL=DEBUG` in `.env` for verbose event logging
- **Database reset:** Run `python seed_db.py` to regenerate `crm.db`
- **Hot reload:** Not built-in. Restart `python app.py` after code changes
- **Browser:** Use Chrome/Edge. Firefox AudioWorklet support may vary
- **Microphone:** Must allow mic access. HTTPS required for remote access (Chrome policy)

---

## Azure Resource Setup

### 1. Create Azure AI Foundry Resource

```bash
# Create resource group
az group create --name rg-virtualrm --location swedencentral

# Create AI Services resource (includes Voice Live)
az cognitiveservices account create \
    --name virtualrm-ai \
    --resource-group rg-virtualrm \
    --kind AIServices \
    --sku S0 \
    --location swedencentral
```

### 2. Deploy a Model

Via Azure AI Foundry portal ([ai.azure.com](https://ai.azure.com)):

1. Open your Foundry project
2. Go to **Model catalog** → search for `gpt-4.1-mini`
3. Deploy as **Global Standard** with capacity ≥100 TPM
4. Note the deployment name (use as `VOICE_LIVE_MODEL`)

### 3. Get Credentials

```bash
# Get endpoint
az cognitiveservices account show \
    --name virtualrm-ai \
    --resource-group rg-virtualrm \
    --query properties.endpoint -o tsv

# Get API key
az cognitiveservices account keys list \
    --name virtualrm-ai \
    --resource-group rg-virtualrm \
    --query key1 -o tsv
```

---

## Voice Live Quotas

| Quota | Default | Notes |
|---|---|---|
| NCPM (New Connections Per Minute) | 30 | Rate limit, not concurrency |
| TPM (Tokens Per Minute) | 120K | NCPM × 4,000 |
| Max Session Duration | 60 minutes | Hard limit |

**To increase quotas:** Submit request at [aka.ms/foundry-tools-quota-increase](https://aka.ms/foundry-tools-quota-increase).

---

## Deploying to Azure

### Option 1: Azure Container Apps

```bash
# Build container
docker build -t virtualrm .

# Deploy to Azure Container Apps
az containerapp up \
    --name virtualrm \
    --resource-group rg-virtualrm \
    --image virtualrm \
    --env-vars \
        AZURE_VOICE_LIVE_ENDPOINT=https://... \
        AZURE_VOICE_LIVE_API_KEY=... \
        VOICE_LIVE_MODEL=gpt-4.1-mini
```

**Note:** You'll need to create a Dockerfile (not included in demo):

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server/ ./server/
WORKDIR /app/server
RUN python seed_db.py
EXPOSE 8000
CMD ["python", "app.py"]
```

### Option 2: Azure App Service

```bash
# Create App Service plan
az appservice plan create \
    --name virtualrm-plan \
    --resource-group rg-virtualrm \
    --sku B1 --is-linux

# Create web app
az webapp create \
    --name virtualrm-app \
    --resource-group rg-virtualrm \
    --plan virtualrm-plan \
    --runtime "PYTHON:3.11"

# Configure
az webapp config appsettings set \
    --name virtualrm-app \
    --resource-group rg-virtualrm \
    --settings \
        AZURE_VOICE_LIVE_ENDPOINT=https://... \
        AZURE_VOICE_LIVE_API_KEY=... \
        VOICE_LIVE_MODEL=gpt-4.1-mini

# Deploy
az webapp deploy \
    --name virtualrm-app \
    --resource-group rg-virtualrm \
    --src-path . \
    --type zip
```

**Important for App Service:** WebSocket support must be enabled:
```bash
az webapp config set --name virtualrm-app --resource-group rg-virtualrm --web-sockets-enabled true
```

### Using Managed Identity (recommended for Azure deployment)

```bash
# Assign system identity
az webapp identity assign --name virtualrm-app --resource-group rg-virtualrm

# Grant Cognitive Services User role
PRINCIPAL_ID=$(az webapp identity show --name virtualrm-app --resource-group rg-virtualrm --query principalId -o tsv)
RESOURCE_ID=$(az cognitiveservices account show --name virtualrm-ai --resource-group rg-virtualrm --query id -o tsv)

az role assignment create \
    --assignee $PRINCIPAL_ID \
    --role "Cognitive Services User" \
    --scope $RESOURCE_ID
```

Then remove `AZURE_VOICE_LIVE_API_KEY` from app settings — the app will use Managed Identity automatically.

---

## Troubleshooting

### Common Issues

| Symptom | Cause | Fix |
|---|---|---|
| `Azure Fast Transcription timeout` | Invalid STT language format | Check `input_audio_transcription.language` format |
| `conversation_already_has_active_response` | Race between VAD auto-response and manual `response.create` | Use `_safe_response_create()` instead of direct send |
| Agent stops responding | VAD failed to auto-create response | Watchdog timer handles this automatically |
| `Speech synthesis failed: Internal server error` | Transient Azure TTS error | Retries automatically on next turn |
| Connection drops after ~60s silence | WebSocket idle timeout | Heartbeat monitor notifies browser |
| Hold music plays before agent speaks | `play_hold_music` not deferred | Music is queued in `_pending_hold_music`, plays on `response.done` |
| Agent repeats itself after noise | Watchdog fires on empty transcription | Watchdog skips empty transcriptions |

### Useful Logs

Key log patterns to watch:

```
# Successful handoff
✦ HANDOFF: Anika → Priya [sop=rate_reduction]

# Tool calls
Tool get_active_loans → 572 chars

# Latency
Time to first audio byte: [latency=1328ms]

# Watchdog fired (VAD failed)
⚠️ Watchdog: no response 5s after speech ended

# Dead connection
💔 No Voice Live events for 30s

# Hold music flow
🎵 Hold music queued (5s, will play after response finishes)
🎵 Playing hold music (5s)
🎵 Hold music finished, injecting thank-for-waiting instruction
```

### Debug Mode

Set `LOG_LEVEL=DEBUG` in `.env` to see all Voice Live events including:
- Every `audio.delta` frame
- Unhandled events
- Audio buffer commits
- Watchdog cancellations
