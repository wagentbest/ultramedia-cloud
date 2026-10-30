import os
import uuid
import subprocess
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import yt_dlp

app = FastAPI(title="UltraMedia Cloud - Compresor 24/7")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STORAGE_DIR = os.path.join(BASE_DIR, "downloads")
STATIC_DIR = os.path.join(BASE_DIR, "static")

os.makedirs(STORAGE_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)

app.mount("/files", StaticFiles(directory=STORAGE_DIR), name="files")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

class VideoRequest(BaseModel):
    url: str
    preset: str = "360p"

class MusicRequest(BaseModel):
    url: str
    preset: str = "m4a_ultra"

@app.get("/api/health")
def health_check():
    return {"status": "online", "message": "UltraMedia Cloud activo 24/7"}

@app.get("/api/media")
def list_media():
    items = []
    if os.path.exists(STORAGE_DIR):
        for fname in os.listdir(STORAGE_DIR):
            if not fname.startswith("temp_"):
                fpath = os.path.join(STORAGE_DIR, fname)
                if os.path.isfile(fpath):
                    size_mb = round(os.path.getsize(fpath) / (1024 * 1024), 2)
                    is_audio = fname.endswith(".m4a") or fname.endswith(".mp3")
                    items.append({
                        "filename": fname,
                        "type": "audio" if is_audio else "video",
                        "size_mb": size_mb,
                        "url": f"/files/{fname}"
                    })
    return {"items": sorted(items, key=lambda x: x["filename"], reverse=True)}

# --- ENDPOINT VIDEO ---
@app.post("/api/video/process")
def process_video(req: VideoRequest):
    if not req.url or not req.url.startswith("http"):
        raise HTTPException(status_code=400, detail="URL inválida.")

    job_id = str(uuid.uuid4())[:8]
    temp_input = os.path.join(STORAGE_DIR, f"temp_v_{job_id}.mp4")
    output_filename = f"video_{job_id}.mp4"
    output_path = os.path.join(STORAGE_DIR, output_filename)

    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': temp_input,
        'quiet': True,
        'no_warnings': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(req.url, download=True)
            title = info.get('title', 'Video')
            duration = info.get('duration', 0)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error al descargar: {str(e)}")

    if not os.path.exists(temp_input):
        raise HTTPException(status_code=500, detail="No se pudo obtener el video.")

    orig_mb = round(os.path.getsize(temp_input) / (1024 * 1024), 2)

    scale = "scale=-2:480" if req.preset == "480p" else "scale=-2:360"
    crf = "26" if req.preset == "480p" else "28"
    abitrate = "64k" if req.preset == "480p" else "40k"
    achannels = "2" if req.preset == "480p" else "1"

    cmd = [
        "ffmpeg", "-y", "-i", temp_input,
        "-vf", scale, "-c:v", "libx264", "-crf", crf, "-preset", "fast",
        "-c:a", "aac", "-b:a", abitrate, "-ac", achannels,
        "-movflags", "+faststart", output_path
    ]

    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Error en compresión de video.")
    finally:
        if os.path.exists(temp_input):
            try: os.remove(temp_input)
            except: pass

    comp_mb = round(os.path.getsize(output_path) / (1024 * 1024), 2)
    saved = round((1 - (comp_mb / max(orig_mb, 0.01))) * 100, 1)

    return {
        "status": "success",
        "title": title,
        "duration": duration,
        "original_size_mb": orig_mb,
        "compressed_size_mb": comp_mb,
        "saved_percent": max(0, saved),
        "filename": output_filename,
        "download_url": f"/files/{output_filename}"
    }

# --- ENDPOINT MUSICA ---
@app.post("/api/music/process")
def process_music(req: MusicRequest):
    if not req.url or not req.url.startswith("http"):
        raise HTTPException(status_code=400, detail="URL inválida.")

    job_id = str(uuid.uuid4())[:8]
    temp_prefix = os.path.join(STORAGE_DIR, f"temp_m_{job_id}")

    if req.preset == "m4a_stereo":
        ext, codec, bitrate, ch = "m4a", "aac", "64k", "2"
    elif req.preset == "mp3_light":
        ext, codec, bitrate, ch = "mp3", "libmp3lame", "96k", "2"
    else:
        ext, codec, bitrate, ch = "m4a", "aac", "48k", "1"

    output_filename = f"music_{job_id}.{ext}"
    output_path = os.path.join(STORAGE_DIR, output_filename)

    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': temp_prefix + ".%(ext)s",
        'quiet': True,
        'no_warnings': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(req.url, download=True)
            title = info.get('title', 'Canción')
            artist = info.get('uploader', 'Artista')
            thumbnail = info.get('thumbnail', '')
            duration = info.get('duration', 0)

            downloaded = None
            for f in os.listdir(STORAGE_DIR):
                if f.startswith(f"temp_m_{job_id}"):
                    downloaded = os.path.join(STORAGE_DIR, f)
                    break
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error al descargar audio: {str(e)}")

    if not downloaded or not os.path.exists(downloaded):
        raise HTTPException(status_code=500, detail="No se encontró el audio.")

    orig_mb = round(os.path.getsize(downloaded) / (1024 * 1024), 2)

    cmd = ["ffmpeg", "-y", "-i", downloaded, "-vn", "-c:a", codec, "-b:a", bitrate, "-ac", ch, output_path]

    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Error en compresión de audio.")
    finally:
        if downloaded and os.path.exists(downloaded):
            try: os.remove(downloaded)
            except: pass

    comp_mb = round(os.path.getsize(output_path) / (1024 * 1024), 2)
    saved = round((1 - (comp_mb / max(orig_mb, 0.01))) * 100, 1)

    return {
        "status": "success",
        "title": title,
        "artist": artist,
        "thumbnail": thumbnail,
        "duration": duration,
        "format": ext.upper(),
        "original_size_mb": orig_mb,
        "compressed_size_mb": comp_mb,
        "saved_percent": max(0, saved),
        "filename": output_filename,
        "download_url": f"/files/{output_filename}"
    }

@app.delete("/api/media/{filename}")
def delete_media(filename: str):
    fpath = os.path.join(STORAGE_DIR, filename)
    if os.path.exists(fpath):
        os.remove(fpath)
        return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="Archivo no encontrado.")

@app.get("/manifest.json")
def get_manifest():
    return FileResponse(os.path.join(STATIC_DIR, "manifest.json"), media_type="application/manifest+json")

@app.get("/favicon.ico")
def get_favicon():
    return FileResponse(os.path.join(STATIC_DIR, "icon-192.png"), media_type="image/png")

@app.get("/")
def serve_index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=False)
