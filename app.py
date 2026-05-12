import streamlit as st
import os
import subprocess
import tempfile
import time
import traceback
import requests
import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted
from dotenv import load_dotenv

load_dotenv()


def parse_time_to_seconds(t: str) -> float:
    parts = t.strip().split(":")
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return float(parts[0])


def log(msg: str):
    st.write(msg)
    print(msg)


def download_video(url: str, out_dir: str) -> tuple[bool, str, str, str]:
    """Download to out_dir. Returns (success, actual_file_path, stdout, stderr)."""
    output_template = os.path.join(out_dir, "video.%(ext)s")
    cmd = [
        "yt-dlp",
        "--no-playlist",
        "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "--merge-output-format", "mp4",
        "--verbose",
        "-o", output_template,
        url,
    ]
    log(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)

    # Find the downloaded file
    downloaded = [
        os.path.join(out_dir, f)
        for f in os.listdir(out_dir)
        if f.startswith("video.")
    ]
    file_path = downloaded[0] if downloaded else ""

    if result.returncode != 0 or not file_path:
        return False, "", result.stdout, result.stderr

    size = os.path.getsize(file_path)
    if size == 0:
        return False, "", result.stdout, result.stderr + "\n[ERROR] Downloaded file is 0 bytes."

    return True, file_path, result.stdout, result.stderr


def clip_video(input_path: str, start: float, duration: float, output_path: str) -> tuple[bool, str]:
    """Returns (success, stderr)."""
    cmd = [
        "ffmpeg",
        "-i", input_path,
        "-ss", str(start),
        "-t", str(duration),
        "-c:v", "libx264",
        "-c:a", "aac",
        output_path,
        "-y",
    ]
    log(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    return result.returncode == 0, result.stderr


GEMINI_MODEL = "gemini-2.5-flash"
MAX_RETRIES = 6
RETRY_DELAY = 25  # seconds


def generate_with_retry(model, contents) -> str:
    """Call model.generate_content with fixed 25s retry on rate limit errors."""
    for attempt in range(MAX_RETRIES):
        try:
            response = model.generate_content(contents)
            return response.text
        except ResourceExhausted:
            if attempt == MAX_RETRIES - 1:
                raise
            log(f"Rate limited (attempt {attempt + 1}/{MAX_RETRIES}). Retrying in {RETRY_DELAY}s...")
            time.sleep(RETRY_DELAY)
    raise RuntimeError("Max retries exceeded")


def generate_content(api_key: str, video_path: str, start_time: str, end_time: str) -> str:
    genai.configure(api_key=api_key)

    log(f"Uploading to Gemini ({GEMINI_MODEL})...")
    video_file = genai.upload_file(video_path, mime_type="video/mp4")

    while video_file.state.name == "PROCESSING":
        time.sleep(2)
        video_file = genai.get_file(video_file.name)

    if video_file.state.name != "ACTIVE":
        raise ValueError(f"Gemini video processing failed: {video_file.state.name}")

    model = genai.GenerativeModel(GEMINI_MODEL)

    prompt = f"""You are a social media content creator for a TikTok channel called HotViews.

Watch this video clip and generate content in EXACTLY this format — no extra text before or after:

{start_time} - {end_time}

Title: [Catchy, specific title about the video content]

Description: [1-2 sentence description with relevant emojis and a country flag emoji if location is identifiable]

Caption:
[2-3 sentence engaging caption that hooks viewers, with relevant emojis]

#[Hashtag1] #[Hashtag2] #[Hashtag3] #[Hashtag4] #[Hashtag5]

Rules:
- Title: 5-8 words, punchy and specific
- Description: ends with flag emoji if location is identifiable
- Caption: present tense, energetic, viewer-focused
- Hashtags: 4-6, highly relevant to the content
- Match the tone and energy of the video"""

    text = generate_with_retry(model, [video_file, prompt])

    try:
        genai.delete_file(video_file.name)
    except Exception:
        pass

    return text


def send_to_telegram(text: str, token: str, chat_id: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = requests.post(url, json={"chat_id": chat_id, "text": text})
    resp.raise_for_status()


# ── UI ────────────────────────────────────────────────────────────────────────

st.set_page_config(page_title="HotViews", page_icon="fire", layout="centered")

st.title("HotViews")
st.caption("Generate TikTok captions and titles with Gemini AI")

gemini_key = os.getenv("GEMINI_API_KEY", "")

with st.sidebar:
    st.header("Telegram")
    tg_token = st.text_input("Bot Token", type="password", placeholder="123456:ABC...")
    tg_chat_id = st.text_input("Chat ID", placeholder="-100123456789")
    st.caption("Get your bot token from @BotFather. Find your chat ID via getUpdates.")

# ── Video source ──────────────────────────────────────────────────────────────
st.subheader("Video Source")
uploaded_file = st.file_uploader("Upload video file", type=["mp4", "mov", "avi", "mkv"])

st.markdown("<div style='text-align:center;color:gray;margin:4px 0'>— or —</div>", unsafe_allow_html=True)

tiktok_url = st.text_input("TikTok URL (fallback if upload not available)", placeholder="https://www.tiktok.com/@...")

# ── Time range ────────────────────────────────────────────────────────────────
st.subheader("Time Range")
col1, col2 = st.columns(2)
with col1:
    start_time = st.text_input("Start Time", placeholder="0:00")
with col2:
    end_time = st.text_input("End Time", placeholder="0:13")

if st.button("Generate Caption & Title", type="primary", use_container_width=True):
    errors = []
    if not gemini_key:
        errors.append("Gemini API key is missing — contact the app owner.")
    if not uploaded_file and not tiktok_url:
        errors.append("Upload a video file or provide a TikTok URL.")
    if not start_time or not end_time:
        errors.append("Enter both start and end times.")
    if not tg_token or not tg_chat_id:
        errors.append("Enter your Telegram Bot Token and Chat ID in the sidebar.")

    if errors:
        for e in errors:
            st.error(e)
    else:
        try:
            start_sec = parse_time_to_seconds(start_time)
            end_sec = parse_time_to_seconds(end_time)

            if end_sec <= start_sec:
                st.error("End time must be after start time.")
            else:
                duration = end_sec - start_sec
                tmp_dir = tempfile.mkdtemp()
                clip_path = os.path.join(tmp_dir, "clip.mp4")
                source_ok = False
                clip_ok = False
                result = ""

                try:
                    with st.status("Processing...", expanded=True) as status:

                        # ── Step 1: Get source video ──────────────────────
                        if uploaded_file:
                            log("Step 1/3 — Saving uploaded file...")
                            raw_path = os.path.join(tmp_dir, "source" + os.path.splitext(uploaded_file.name)[1])
                            with open(raw_path, "wb") as f:
                                f.write(uploaded_file.read())
                            raw_size = os.path.getsize(raw_path)
                            log(f"Upload OK — {raw_size / 1024 / 1024:.2f} MB")
                            source_ok = True
                        else:
                            log("Step 1/3 — Downloading via yt-dlp (fallback)...")
                            source_ok, raw_path, dl_stdout, dl_stderr = download_video(tiktok_url, tmp_dir)
                            with st.expander("yt-dlp output"):
                                st.code(dl_stdout or "(no stdout)")
                                st.code(dl_stderr or "(no stderr)")
                            if not source_ok:
                                status.update(label="Failed at download", state="error")
                                st.error("yt-dlp failed. See output above. Try uploading the file directly instead.")

                        # ── Step 2: Clip ──────────────────────────────────
                        if source_ok:
                            log(f"Step 2/3 — Clipping {start_time} to {end_time} ({duration:.1f}s)...")
                            clip_ok, ffmpeg_stderr = clip_video(raw_path, start_sec, duration, clip_path)
                            with st.expander("ffmpeg output"):
                                st.code(ffmpeg_stderr or "(no output)")
                            if not clip_ok:
                                status.update(label="Failed at clip", state="error")
                                st.error("ffmpeg failed. See output above for details.")
                            else:
                                clip_size = os.path.getsize(clip_path) if os.path.exists(clip_path) else 0
                                log(f"Clip OK — {clip_size / 1024:.1f} KB")

                        # ── Step 3: Gemini + Telegram ─────────────────────
                        if source_ok and clip_ok:
                            log("Step 3/3 — Uploading to Gemini and generating content...")
                            result = generate_content(gemini_key, clip_path, start_time, end_time)
                            log("Gemini OK. Sending to Telegram...")
                            send_to_telegram(result, tg_token, tg_chat_id)
                            log("Telegram OK.")
                            status.update(label="Done!", state="complete")

                    if source_ok and clip_ok:
                        st.divider()
                        st.subheader("Generated Content")
                        st.text_area("Copy:", result, height=300)
                        st.divider()
                        st.markdown(result)

                finally:
                    if os.path.exists(clip_path):
                        os.unlink(clip_path)

        except Exception as e:
            st.error(f"Error: {e}")
            with st.expander("Full traceback"):
                st.code(traceback.format_exc())
