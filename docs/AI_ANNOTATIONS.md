# AI Annotations & Insights

The TreeSight system includes AI-powered analysis of satellite imagery using a local LLM running in Docker with Nvidia GPU support.

## Setup: Ollama in Docker (Recommended)

### Prerequisites

1. **Nvidia GPU** with CUDA support
2. **Nvidia Docker Runtime** - Install nvidia-docker:

   ```bash
   distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
   curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
   curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | \
     sudo tee /etc/apt/sources.list.d/nvidia-docker.list
   sudo apt-get update && sudo apt-get install -y nvidia-docker2
   sudo systemctl restart docker
   ```

3. **Verify Docker GPU access**:

   ```bash
   docker run --rm --runtime=nvidia nvidia/cuda:12.1.1-runtime-ubuntu22.04 nvidia-smi
   ```

### Start with GPU Support

The Ollama container is included in `docker-compose.yml`. Simply start the full stack:

```bash
make dev-up
```

Or manually:

```bash
docker compose up -d
```

The Ollama service will:

- Start on port `11434`
- Use Nvidia GPU automatically
- Auto-pull the `mistral` model on first run (~4GB)
- Persist models in `ollama-data` volume

### (Legacy) Standalone Ollama Setup

If running Ollama outside Docker:

1. **Install Ollama**: <https://ollama.ai>
2. **Start service**: `ollama serve`
3. **Pull model**: `ollama pull mistral`
4. **Configure Functions** to use local LLM:

## Using AI Annotations

1. **Upload a KML file** and process it as usual
2. **Navigate to a frame** in the timelapse
3. **Click "Get AI Insights for Current Frame"** button in the 🤖 AI Analysis panel
4. The LLM analyzes:
   - Current & previous NDVI values
   - Vegetation health trends
   - Temperature & precipitation context
   - Date/location context
5. Observations are displayed with **severity levels** and **recommendations**

## What the AI Analyzes

Based on satellite metadata (not image pixels), the LLM generates observations about:

- **Vegetation Health** - NDVI trends, recovery, stress
- **Clearing Detection** - Significant NDVI drops
- **Seasonal Patterns** - Weather vs. vegetation correlation
- **Anomalies** - Unusual changes or patterns
- **Trends** - Long-term changes over the timelapse

## Example Output

```json
{
  "observations": [
    {
      "category": "vegetation_health",
      "severity": "moderate",
      "description": "NDVI declined 0.12 from previous frame (0.52 → 0.40)",
      "recommendation": "Monitor area for land clearing or stress"
    },
    {
      "category": "trend",
      "severity": "low",
      "description": "Gradual spring recovery visible",
      "recommendation": "Continue monitoring seasonal cycle"
    }
  ],
  "summary": "Moderate vegetation change detected. Likely seasonal transition with some stress signals.",
  "score": 0.45
}
```

## Performance

- **Response time**: 2-10 seconds (depends on model & hardware)
- **Model size**: 4-13 GB RAM required
- **Hardware**: Works on CPU, faster on GPU
- **Cost**: 100% local, no API calls

## Troubleshooting

### Connection Refused

- Check Ollama is running: `ollama serve`
- Verify port 11434 is accessible
- Set `OLLAMA_URL` if using non-default host

### Slow Responses

- Try lighter model: `ollama pull neural-chat`
- Or use GPU: Install CUDA/ROCm for Ollama

### OOM Errors

- Reduce model size: `ollama pull mistral:7b`
- Or increase available system memory
