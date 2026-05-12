# HotViews Caption Generator

A Streamlit app that takes a TikTok video URL and a time range, downloads and clips the segment, and uses Gemini AI to generate a formatted caption and title.

## Output Format

```
HotViews

0:00 - 0:13

Title: The Changing Face of Addis

Description: Cruising through the upgraded boulevards and redesigned streets of the capital. 🙌🇪🇹

Caption:
The 2026 transformation is here. High-rises, heritage, and heart all from the top of the bus. Addis Ababa is looking world-class. ✨🏙

#AddisAbaba #ModernEthiopia #Cityscape #Africa2026
```

## Requirements

- Python 3.10+
- ffmpeg installed on your system
- A Gemini API key

## Setup

**1. Install ffmpeg**

```bash
brew install ffmpeg   # macOS
```

**2. Install Python dependencies**

```bash
pip install -r requirements.txt
```

**3. Configure your API key**

Add your Gemini API key to `.env`:

```
GEMINI_API_KEY=your_key_here
```

Get a key at [Google AI Studio](https://aistudio.google.com).

## Run

```bash
streamlit run app.py
```

## Usage

1. Paste a TikTok video URL
2. Enter the start and end time of the clip (e.g. `0:05` and `0:18`)
3. Click **Generate Caption & Title**
4. Copy the output from the text box

## How It Works

1. `yt-dlp` downloads the full TikTok video
2. `ffmpeg` clips the specified segment
3. The clip is uploaded to the Gemini File API
4. `gemini-2.0-flash` watches the clip and generates the formatted content
5. The uploaded file is deleted from Gemini after generation
