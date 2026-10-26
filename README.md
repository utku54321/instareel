LYRIC STUDIO - turn a song into an animated lyric video
=========================================================

FIRST TIME (once only)
  Windows : double-click  install.bat        (15-40 min, mostly downloads)
  Mac/Linux: bash install.sh

EVERY TIME
  Windows : double-click  start.bat          -> the page opens in your browser
  Mac/Linux: bash start.sh                    -> open http://127.0.0.1:8765
  Keep the black window open while you use the page.

ON THE PAGE
  1. Add your song (MP3/WAV/M4A). A 15-60 second clip is best for reels.
  2. Lyrics
       Find automatically : LRCLIB first, then Whisper if the song isn't there.
                            "Clip starts at" = where your clip begins in the full
                            song (needed for LRCLIB timings).
       Type or paste      : one line per row, as  0:05.2 | your line
                            or paste without times and use "Tap timing".
     Always read the lyrics and fix mistakes before making the video.
  3. Size  : Reel 9:16, Square 1:1, or Wide 16:9
  4. Style : Midnight, Highway or Neon Rain (live previews on the cards)
  5. Make video. It records in real time; play Note Catcher while you wait.
     Then pick MP4 Instagram quality, MP4 small, or the original, and Download.

TIPS
  * Use Chrome or Edge, and keep the tab in front while it records.
  * Hindi lyrics in Devanagari become Hinglish only if you saved a Gemini key
    during install (file: gemini_key.txt). Free key: https://aistudio.google.com/apikey
  * Slow laptop? Pick the "medium" or "small" Whisper model on the page.
  * Command-line only:  .venv\Scripts\python make_lyrics.py song.mp3 --whisper-only

FILES
  server.py       local server (lyrics jobs + MP4 conversion)
  make_lyrics.py  LRCLIB -> Demucs + Whisper -> Hinglish -> lyrics.json
  static/index.html  the web page
  install.bat / start.bat (Windows), install.sh / start.sh (Mac/Linux)
